#!/bin/bash
clear
echo 
echo
if [[ $(id -u) -ne 0 ]] ; then
	printf "you need root assess to install necessary packages\n\n"

	printf  "so please enter the password to login as root!\n\n"

	sudo bash ${0}
	printf "\n\n"
	exit
fi
printf "NOTE: you need internet connction to install necessary packages\n"
printf "so please make sure computer is connected to internet\n\n"
for i in 3 2 1
do
	echo "staring installation process in ${i}" ; 
	sleep 1
done
printf "\n\n" 
apt update -y
apt install python3 pip -y
pip3 install requests
rm /usr/bin/aliens_eye &>/dev/null
cp aliens_eye.py /usr/bin/aliens_eye
chmod +x /usr/bin/aliens_eye
printf "\n\ninstalled successfully!"
printf "\nnow run command \"aliens_eye\" in terminal!(without \"\")"