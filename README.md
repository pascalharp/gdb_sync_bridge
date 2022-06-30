# Synchronize two running qemu emulation
This is a small python script to synchronize two running gdb instances. The emulation will single step on both instances and then exchange register values over a socket connection. If the values differ the emulation will stop.

This script is currently written for arm32 emulation but can probably be adapted for other architectures as well.

## Install
Requires a gdb installation that was compiled with python3 support.
 - Download `sync_bridge.py`.
 - Start both gdb instances and source the plug in with `source /path/to/sync_bridge.py`.
 - Initialize the plug in with: `sb_init` on both gdb instances.

## Run
It is recommended to continue the emulation on both gdb instances to a point where they are in the same state.
On one of the emulation call `sb_lead` and afterwards call `sb_follow` on the other gdb instance.
The emulation should now continue until a difference is detected.
