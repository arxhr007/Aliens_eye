#!/bin/bash
clear
echo 
echo
if [[ $(id -u) -ne 0 ]] ; then
	echo "you need root assess to install necessary packages"
	echo
	echo "so please enter the password to login as root!"
	echo
	sudo bash ${0}
	echo 
	echo 
	exit
fi
echo "NOTE: you need internet connction to install necessary packages"
echo "so please make sure computer is connected to internet"
echo
echo
for i in 3 2 1
do
	echo "staring installation process in ${i}" ; 
	sleep 1
done
echo 
echo 
apt update -y
apt install python3 pip -y
pip3 install requests
FILE1=/usr/bin/aliens_eye
if [ -f "$FILE1" ]; then
	rm /usr/bin/aliens_eye
fi
VAR1="${0}"
VAR2="${0##*/}"
if [ "$VAR1" = "$VAR2" ]; then
	cp aliens_eye.py /usr/bin/aliens_eye
else
	cp ${0%/*}/aliens_eye.py /usr/bin/aliens_eye
fi
chmod +x /usr/bin/aliens_eye
echo 
echo
echo "installed successfully!"
echo
echo "now run command \"aliens_eye\" in terminal!(without \"\")"
