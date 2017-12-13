"""Provide access to selected git functions."""

import subprocess

GIT_PATH = '/usr/bin/git'
"""Where to find the "git" command?"""

def get_revision() -> str:
    """return the git revision of current directory as a human-readable string.

    :raises OSError: Couldn't get revision from git.
    """
    try:
        job = subprocess.run([GIT_PATH, 'log', '-1', '--pretty=oneline'],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             timeout=1)
    except subprocess.TimeoutExpired as err:
        raise OSError("Calling git took too long.") from err
    except FileNotFoundError as err:
        raise OSError("Git not found at '{}'.".format(GIT_PATH)) from err
    try:
        ret_string = job.stdout.decode().strip()
        if not ret_string:
            raise OSError("Git returned an empty string. STDERR is {}".format(job.stderr))
        return ret_string
    except AttributeError as err:
        raise OSError("Git didn't return a bytestring, but {} instead.".format(job.stdout)) from err
