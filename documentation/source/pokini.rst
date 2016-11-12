Pokini Z
========
The Pokini Z pocket computer is the experiment control computer that later
becomes part of the payload.

Hardware and OS
---------------
The Pokini is equipped with soldered-in *Intel Atom Z530* CPU, *Intel (Poulsbo)
GMA500* graphics chip and 2GB RAM. This is a i686 system, so no 64bit
capabilities.

There are some pitfalls to be avoided when installing anything higher than a
basic DOS on that machine:

Uncommon graphics chip
^^^^^^^^^^^^^^^^^^^^^^
The built-in graphics chip has a long history of being the only common graphics
chip that doesn't have a working driver for Linux. But as this machine is going
to be used as a server, we don't actually need any graphical output.

For some reason, Ubuntu Server 14.04 and 16.04 try to load the corresponding
kernel module nevertheless, which is why we need to blacklist the module to be
able to boot.
If one can't get into the system at all (as it's not booting, as stated above),
the only fix is to edit the GRUB boot line to include
``modprobe.blacklist=gma500_gfx`` right next to ``ro``.

Once in the system, one can make this change permanent by blacklisting the
faulty module: in `/etc/modprobe.d/blacklist.conf` add a line::

  blacklist gma500_gfx

Motherboard disabling CPU C6 state
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
The Atom Z530 CPU supports falling "asleep" into the C6 power state.
This feature however is neither supported nor exposed by the motherboard used in
the Pokini.
The C6 state thus doesn't work on the Pokini.

This doesn't lead to problems as long as the OS relies on the states that are
exposed by the BIOS. 
Linux however determines allowable C states from inspecting the CPU itself and
thus tries to use the C6 state, leading to hard CPU lock-ups and unrecoverable
kernel panic.
Again, the system won't boot.

The easy way to work around that problem is to get into the BIOS settings and
disable the use of C states altogether. Although this does work, it disables a
central feature of the CPU.

The more elegant workaround is to keep the Linux kernel from using only the
broken C6 state. The other states work fine! To do this we will add a boot
option in the GRUB configuration file as follows::

  GRUB_CMDLINE_LINUX="intel_idle.max_cstate=3"

Storage
^^^^^^^
The Pokini features an internal 250GB PATA SSD storage device. It is formatted
in the MBR scheme, and set up to house two primary partitions.

1. System partition, ~230GiB, formatted as BTRFS
2. Swap partition, ~4GiB, used as swap obviously

On the BTRFS partition, there are multiple subvolumes set up, including

* ``@home``, which is always mounted to ``/home/``
* ``ubuntu16``, which goes to ``/``
* ``ubuntu14``, a "fallback" installation of Ubuntu Server 14.04.5

Software
--------
As they are usually stable and lightweight, Linux server distributions should be
a good choice.
There is an *Ubuntu Server 16.04 LTS* currently booting by default, a 14.04
version is also on the disk as a backup.

Ubuntu was the first choice because it is widespread, which leads to plenty of
tech support being available.
Version 16.04 was chosen in favor of 14.04, as it natively supports Python 3.5,
available via the ``python3`` executable.

.. attention::
  Note that just invoking ``python`` does call the python2 binary which is
  incompatible with parts of the JOKARUS code!

The installation's root password is *root*, furthermore there is a user
*jokarus* (password *jokarus*) which intended to be used instead of the root
account.

Network
-------
The Pokini's host name is "jokarus-server", it is available from within the QOM
subnet as **192.168.1.85**, so just

.. code-block:: bash

  ssh jokarus@192.168.1.85

and you're good to go.
