import sys
import subprocess

class GitError(Exception):
    pass

class GitParseError(Exception):
    pass

class Git(object):
    def rev_list(self, commits):
        proc = subprocess.Popen(('git', 'rev-list', '--parents') + tuple(commits),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
        stdoutdata, stderrdata = proc.communicate()
        if proc.returncode != 0:
            raise GitError('rev-list')
        return [{'hash': tok[0], 'parents': tok[1:]}
                for line in stdoutdata.decode().splitlines()
                for tok in (line.split(),)]

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

def main(base, upstream):
    git = Git()
    commits = commit_chain(git, base, upstream)
    first = commits[0]
    result = DependencyGraph().add_root(first)

if __name__ == '__main__':
    main(*sys.argv[1:])
