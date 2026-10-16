"""Zet PR_SET_PDEATHSIG en start daarna het gegeven programma.

Dit is een eigen proces, gestart vóór nginx. preexec_fn in de app zelf is
onveilig zodra er threads zijn. Dit proces heeft die niet. Sterft de ouder
(ook door SIGKILL), dan krijgt dit proces SIGTERM. De instelling blijft
staan na exec, dus nginx sterft mee.
"""
import ctypes
import os
import signal
import sys


def main():
    if len(sys.argv) < 2:
        sys.exit(127)
    ouder = os.getppid()
    libc = ctypes.CDLL(None, use_errno=True)
    # 1 = PR_SET_PDEATHSIG
    if libc.prctl(1, int(signal.SIGTERM)) != 0:
        sys.exit(126)
    if os.getppid() != ouder:
        os.kill(os.getpid(), signal.SIGTERM)
        sys.exit(125)
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
