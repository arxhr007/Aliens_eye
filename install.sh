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
apt install python3 pip
pip3 install requests
FILE=/usr/share/aliens_eye.py
if [ -f "$FILE" ]; then
	rm /usr/share/aliens_eye.py
fi
cp ${0%/*}/aliens_eye.py /usr/share/aliens_eye.py
FILE1=/usr/bin/aliens_eye
if [ -f "$FILE1" ]; then
	rm /usr/bin/aliens_eye
fi
echo "python3 /usr/share/aliens_eye.py" > /usr/bin/aliens_eye
chmod +x /usr/bin/aliens_eye
echo 
echo
echo "installed successfully!"
echo
echo "now run command \"aliens_eye\" in terminal!(without \"\")"
