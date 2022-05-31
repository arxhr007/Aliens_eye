#!/bin/bash
clear
printf "\n\n"
printf "NOTE: you also need install necessary packages in requirements.txt\n"                                 for i in 3 2 1
do
        echo "staring installation process in ${i}" ;          sleep 1
done
printf "\n\n"
rm /data/data/com.termux/files/usr/bin/aliens_eye &>/dev/null
cp aliens_eye.py /data/data/com.termux/files/usr/bin/aliens_eye
chmod +x /data/data/com.termux/files/usr/bin/aliens_eye
printf "\n\ninstalled successfully!"
