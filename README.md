isohunt-grab
=========================

Seesaw script for the Archive Team Isohunt grabbing.
You'll find this project on the Archive Team Warrior (http://tracker.archiveteam.org/isoprey/).


Running without a warrior
-------------------------

To run this outside the warrior, clone this repository and run:

    pip install seesaw
    ./get-wget-lua.sh

then start downloading with:

    run-pipeline pipeline.py YOURNICKNAME

For more options, run:

    run-pipeline --help

Distribution-specific setup
-------------------------

### For Debian:

Be sure to replace `YOURNICKHERE` with your nickname.

    adduser --system --group --shell /bin/bash archiveteam
    apt-get install -y git-core libgnutls-dev lua5.1 liblua5.1-0 liblua5.1-0-dev screen python-pip
    pip install seesaw
    su -c "cd /home/archiveteam; git clone https://github.com/joepie91/isohunt-grab.git; cd isohunt-grab; ./get-wget-lua.sh" archiveteam
    screen su -c "cd /home/archiveteam/isohunt-grab/; run-pipeline pipeline.py --concurrent 2 --address '127.0.0.1' YOURNICKHERE" archiveteam
    [... ctrl+A D to detach ...]
    
### For CentOS:

    yum -y install gnutls-devel lua-devel python-pip
    pip install seesaw
    [... pretty much the same as above ...]

### For OS X:

You need Homebrew.

**There is a known issue with some packaged versions of rsync. If you get errors during the upload stage, isohunt-grab will not work with your rsync version.**

    brew install python lua
    pip install seesaw
    [... pretty much the same as above ...]

### For Arch Linux:

1. Make sure you have `python-pip2` installed.
2. Install [https://aur.archlinux.org/packages/wget-lua/](the wget-lua package from the AUR). 
3. Run `pip2 install seesaw`.
4. Modify the run-pipeline script in seesaw to point at `#!/usr/bin/python2` instead of `#!/usr/bin/python`.
5. `adduser --system --group --shell /bin/bash archiveteam`
6. `screen su -c "cd /home/archiveteam/isohunt-grab/; run-pipeline pipeline.py --concurrent 2 --address '127.0.0.1' YOURNICKHERE" archiveteam`
