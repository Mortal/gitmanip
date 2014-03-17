import sys
import subprocess
import itertools

class GitError(Exception):
    """Git could not execute the command."""
    pass

class GitParseError(Exception):
    """Could not parse the output from git."""
    pass

class PatchError(Exception):
    """Patch failed to apply cleanly."""
    pass

class GitObject(object):
    def __init__(self, git, rep):
        self._git = git
        self._rep = rep

    def parse(self):
        return self._git.rev_parse(str(self))

    def force(self):
        return GitObject(self._git, self.parse())

    def __str__(self):
        return self._rep

    def __repr__(self):
        return str(self)

class Git(object):
    def _gitcmd(self, args, input=None):
        print("")
        print(">>> git %s" % ' '.join(args))
        proc = subprocess.Popen(('git',) + tuple(args),
                stdin=subprocess.PIPE if input else subprocess.DEVNULL, stdout=subprocess.PIPE)
        stdoutdata, stderrdata = proc.communicate(input=input.encode() if input is not None else None)
        return proc.returncode, stdoutdata.decode()

    def _gitcmd_ensure(self, args, input=None):
        returncode, stdoutdata = self._gitcmd(args, input=input)
        if returncode != 0:
            raise GitError(args[0])
        return stdoutdata

    def _log_head(self):
        h = self.head()
        print("<<< %s" % h)
        return h

    def rev_list(self, commits):
        stdoutdata = self._gitcmd_ensure(('rev-list', '--parents') + tuple(map(str, commits)))
        return [{'hash': tok[0], 'parents': tok[1:]}
                for line in stdoutdata.splitlines()
                for tok in (line.split(),)]

    def checkout(self, commit):
        self._gitcmd_ensure(('checkout', '-f', str(commit)))

    def rev_parse(self, commit):
        stdoutdata = self._gitcmd_ensure(('rev-parse', str(commit)))
        return stdoutdata.strip()

    def cherry_pick(self, commit):
        returncode, stdoutdata = self._gitcmd(('cherry-pick', str(commit)))
        if returncode != 0:
            self._gitcmd(('cherry-pick', '--abort'))
            raise PatchError()
        return self._log_head()

    def merge(self, commit1, commit2):
        self.checkout(commit1)
        returncode, stdoutdata = self._gitcmd(('merge', '-m', "Merge by Git.merge", str(commit2)))
        if returncode != 0:
            self._gitcmd(('merge', '--abort'))
            raise PatchError()
        return self._log_head()

    def forge_merge(self, treeish, commits):
        stdoutdata = self._gitcmd_ensure(
                ('commit-tree', '%s^{tree}' % treeish)
                + tuple(itertools.chain.from_iterable(('-p', str(commit))
                    for commit in commits)),
                input='Forged merge')
        return stdoutdata.strip()

    def head(self):
        return GitObject(self, 'HEAD').force()

class DependencyGraph(object):
    def __init__(self, roots=None, edges=None):
        self._roots = frozenset(roots or [])
        self._edges = frozenset(edges or [])

    def add_root(self, root, hides=None):
        return DependencyGraph(
                roots=self._roots.difference((hides,)),
                hides=self._hides.union(((root, hidee) for hidee in hides or ())))

def commit_chain(git, base, upstream):
    commits = git.rev_list(('^'+base, upstream))
    if list(filter(lambda commit: len(commit['parents']) != 1, commits)):
        raise GitParseError('rev-list')
    if ([commit['hash'][:7] for commit in commits[1:]] !=
            [commit['parents'][0][:7] for commit in commits[:-1]]):
        raise GitParseError('rev-list')
    return [commit['hash'] for commit in reversed(commits)]

def ensure_patch_applies(git, commit, root):
    git.checkout(root)
    return git.cherry_pick(commit)

def check_patch_applies(git, commit, root):
    try:
        ensure_patch_applies(git, commit, root)
        return True
    except PatchError:
        return False

def apply_patch(git, commit, root):
    simple_apply = ensure_patch_applies(git, commit, root['commit'])
    if len(root['parents']) == 0:
        # Special case when root == upstream
        return {'commit': simple_apply, 'parents': [root]}
    elif len(root['parents']) == 1:
        parent, = root['parents']
        try:
            recurse = apply_patch(git, commit, parent)
            return {'commit': git.merge(root['commit'], recurse['commit']), 'parents': [root, recurse]}
        except PatchError:
            return {'commit': simple_apply, 'parents': [root]}
    elif len(root['parents']) == 2:
        p1, p2 = root['parents']
        try:
            r1 = apply_patch(git, commit, p1)
        except PatchError:
            r1 = None
        try:
            r2 = apply_patch(git, commit, p2)
        except PatchError:
            r2 = None
        if r1 is None and r2 is None:
            return {'commit': simple_apply, 'parents': [root]}
        elif r2 is None:
            return {'commit': git.merge(r1['commit'], p2['commit']), 'parents': [r1, p2]}
        else:
            return {'commit': git.merge(p1['commit'], r2['commit']), 'parents': [p1, r2]}

def flatten_merges(git, root):
    if len(root['parents']) == 0:
        return root
    elif len(root['parents']) == 1:
        parent, = root['parents']
        flattened = flatten_merges(git, parent)
        commit = ensure_patch_applies(git, root['commit'], flattened['commit'])
        return {'commit': commit, 'parents': [flattened]}
    else:
        parents = []
        for parent in root['parents']:
            flattened = flatten_merges(git, parent)
            if len(flattened['parents']) > 1:
                parents += flattened['parents']
            else:
                parents.append(parent)
        if len(parents) > 2:
            commit = git.forge_merge(
                    root['commit'],
                    [parent['commit'] for parent in parents])
            return {'commit': commit, 'parents': parents}
        else:
            return root

def main(base_hash, upstream):
    git = Git()
    commits = commit_chain(git, base_hash, upstream)

    root = {'commit': base_hash, 'parents': []}

    for commit in commits:
        root = apply_patch(git, commit, root)

    root_unflatten = root

    root = flatten_merges(git, root)

    print("Unflattened result: %s" % root_unflatten['commit'])
    print("Flattened result: %s" % root['commit'])

if __name__ == '__main__':
    main(*sys.argv[1:])
