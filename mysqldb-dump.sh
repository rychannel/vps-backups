#!/bin/bash

set +e

##############################################################
##Based on script provided by Chris Alman                   ##
##Modified to backup individual databases rather than tables##
##This version retains one copy of the databases.           ##
##Ryan Murphy Jan 25,2013                                   ##
##############################################################



#########################
######TO BE MODIFIED#####

### System Setup ###
#BACKUP=/home/drupaldump/prod-mysqldump/titan/new-backups

### MySQL Setup ###
MUSER="root"
MPASS="%Python-74656"
MHOST="localhost"

## Locations
DUMPDIR=/home/ec2-user/db-dumps

#Directory files are backed up to
DESTDIR=/root/vps-mysql

### Shouldn't have to modify below ###

## Binaries ##

TAR="/bin/tar"
GZIP="/bin/gzip"
MYSQL="/usr/bin/mysql"
MYSQLDUMP="/usr/bin/mysqldump"

echo "Clearing old dumps..."
/usr/bin/find ${DUMPDIR} -mindepth 1 -maxdepth 1 -mtime 0 -exec /bin/rm {} \;
/usr/bin/find ${DUMPDIR} -mindepth 1 -maxdepth 1 -mtime +0 -exec /bin/rm {} \;
echo "Dumps cleared."


#DAILY=${DUMPDIR}daily/
#WEEKLY=${DUMPDIR}weekly/
#MONTHLY=${DUMPDIR}monthly/


### Today + hour:minute###

NOW=$(/bin/date +%Y%m%d-%H%M)

### Create daily tmp directory ###

#mkdir $DAILY/$MHOST-$NOW

### Get all databases name ###
DBS="$($MYSQL -u $MUSER -h $MHOST -p$MPASS -Bse 'show databases')"

for db in $DBS
do
### Dump databases ###
    if [ $db != "information_schema" ] && [ $db != "performance_schema" ];
    then
        FILE=${DUMPDIR}/$db.sql.gz
        echo Writing... $FILE
        $MYSQLDUMP -h $MHOST -u$MUSER -p$MPASS $db | $GZIP > $FILE
    fi
done

echo ''
#echo 'Executing rdiff-backup...'

#/usr/bin/rdiff-backup ${DUMPDIR} ${DESTDIR}

#echo 'Backup complete.'

#echo 'Removing backups older than 2 Months...'

#/usr/bin/rdiff-backup --force --remove-older-than 2M ${DESTDIR}

echo 'Process Complete.'

### Create Weekly backups ###
#if [ $(date +%A) = Sunday ]
#then
#    echo "Creating Weekly Backup"
#    find ${DAILY} -mindepth 1 -maxdepth 1 -type d -mtime 0 -exec cp -r {} ${WEEKLY} \;
#fi

### Create Monthly Backups ###
#if [ $(date +%d) = 01 ]
#then
#    echo "Creating monthly backup..."
#    find ${DAILY} -mindepth 1 -maxdepth 1 -type d -mtime 0 -exec cp -r {} ${MONTHLY} \;
#fi
#
## Cleanup old backups ##

#find ${DUMPDIR} -mindepth 1 -maxdepth 1 -type d -mtime +1 -exec rm -r {} \;

#find ${WEEKLY} -mindepth 1 -maxdepth 1 -type d -mtime +28 -exec rm -r {} \;

#find ${MONTHLY} -mindepth 1 -maxdepth 1 -type d -mtime +365 -exec rm -r {} \;
