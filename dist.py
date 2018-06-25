import os
import re
import types
import sys
import logging
import platform
import glob

from paramiko.pkey import PKey
from paramiko.rsakey import RSAKey
from paramiko.sftp_client import SFTPClient
from paramiko.transport import Transport

from yumcommands import YumCommand
from yum.Errors import YumBaseError
from yum.plugins import TYPE_CORE, TYPE_INTERACTIVE

from paramiko.message import Message
from paramiko.sftp import CMD_OPENDIR, CMD_HANDLE, SFTPError, CMD_READDIR, CMD_NAME, CMD_CLOSE
from paramiko.sftp_client import _to_unicode
from paramiko.sftp_attr import SFTPAttributes
from pprint import pprint


requires_api_version = '2.4'
plugin_type = (TYPE_CORE, TYPE_INTERACTIVE)

branch_list = set(["test", "current", "stable"])
debuginfo_list = set(["debug", "debuginfo"])
arch_list = set(["x86-64", "noarch"])


_repository_prefix = None
_repository_server = None
_repository_port = 22
_repository_user = None
_repository_path = None
_identity_file = None
_sftp_client = None


class DistPushError(YumBaseError):
    pass

class DistMoveError(YumBaseError):
    pass

class DistRemoveError(YumBaseError):
    pass

class DistExistsError(YumBaseError):
    pass

class DistSFTPClient(SFTPClient):

    def listdir_ex(self, path):
        path = self._adjust_cwd(path)
        basename = os.path.basename(path);
        dir = os.path.dirname(path)
        t, msg = self._request(CMD_OPENDIR, dir)
        if t != CMD_HANDLE:
            raise SFTPError('Expected handle')
        handle = msg.get_string()
        filelist = []
        while True:
            try:
                t, msg = self._request(CMD_READDIR, handle)
            except EOFError:
                # done with handle
                break
            if t != CMD_NAME:
                raise SFTPError('Expected name response')
            count = msg.get_int()
            for i in range(count):
                filename = _to_unicode(msg.get_string())
                longname = _to_unicode(msg.get_string())
                attr = SFTPAttributes._from_msg(msg, filename, longname)
                if (filename != '.') and (filename != '..') and filename.startswith(basename):
                    filelist.append(filename)
        self._request(CMD_CLOSE, handle)
        return filelist



def get_sftp_client():
    global _sftp_client, _identity_file, _repository_server, _repository_port, _repository_user
    try:
        if not _sftp_client:
            key = RSAKey.from_private_key_file(_identity_file)
            t = Transport((_repository_server, _repository_port))
            t.connect(username = _repository_user, pkey = key)
            _sftp_client = DistSFTPClient.from_transport(t)
    except Exception, e:
        print e
    return _sftp_client

def create_sftp_dir(sftp_client, path):
    if path and path[len(path) - 1] == '/':
        path = path[:-1]
    dirs_to_create = []
    while path:
        try :
            stat = sftp_client.stat(path)
            break
        except Exception, e:
            dirs_to_create.append(path)
            path = os.path.dirname(path)

    dirs_to_create.reverse()

    try :
        for file in dirs_to_create:
            sftp_client.mkdir(file)
    except Exception, e:
        print e

def create_sftp_symlink(sftp_client, path, filename, overwrite):
    create_sftp_dir(sftp_client, path)
    
    source_file = sftp_client.normalize(path + "/../../packages/" + filename)
    dest_file = path + "/" + filename

    if is_file_exists(sftp_client, dest_file, overwrite):
        raise DistExistsError, "file %s exists in repository!"%(filename)
    
    sftp_client.chdir(path)
    sftp_client.symlink(source_file, filename)

# sftp_client
# format 
# branc_list
# remove
def is_file_exists(sftp_client, file, overwrite):
    try :
        stat = sftp_client.stat(file)
        if overwrite:
            sftp_client.remove(file)
        else:
            return True
    except Exception:
        pass
    return False

def guess_rpm_files(sftp_client, osver, arch, branch, file):
    global _repository_path
    try :
        path = "%s/%d/%s/%s/packages/%s"%(_repository_path, osver, arch, branch, file)
        return sftp_client.listdir_ex(path)
    except Exception, e:
        print e
    return None

def update_last_modify_time(sftp_client, osver, arch, branch):
    global _repository_path
    try :
        file = "%s/%d/%s/%s/last_modify_time"%(_repository_path, osver, arch, branch)
        sftp_client.utime(file, None)
    except Exception, e:
        obj = sftp_client.open(file, "w", 0)
        obj.close()
        print e
    return True

# yum dist-push
# yum dist-move
# yum dist-remove
class DistPushCommand(YumCommand):
    def getNames(self):
        return ['dist-push', 'dist-add']

    def getUsage(self):
        return ("PACKAGE...")

    def getSummary(self):
        return ("Push the rpm packages to repository via sftp")

    def doCheck(self, base, basecmd, extcmds):
        pass

    def doCommand(self, base, basecmd, extcmds):
        logger = logging.getLogger("yum.verbose.main");
        
        opts = base.plugins.cmdline[0]

        print "================================\n"

        # get the branch
        branch = opts.branch
        if len(base.plugins.cmdline[1]) <= 1:
            raise DistPushError, "Must specify at least one package to be push (i.e yum dist-push --branch <branch> pkg)";
        elif not branch or branch not in branch_list:
            while branch not in branch_list:
                branch = raw_input("Push the packages to which branch? [test] : ");
                if branch == "":
                    branch = "test"
        else:
            branch = opts.branch

        osver = None
        if opts.osver:
            osver = int(opts.osver)
            if (osver < 6) or (osver > 10):
                raise DistPushError, "osver must be a number, and between 6 and 10"
        
        if not osver:
            osver = platform.dist()[1]
            osver = int(osver[0:osver.index(".")])


        # test/x86_64/packages
        rpm_files = []

        cmd_lines = base.plugins.cmdline[1][1:]
        for i in cmd_lines:
            rpm_files = rpm_files + glob.glob(i)

        # filter the duplicate files
        rpm_files = list(set(rpm_files))

        sftp_client = get_sftp_client()

        global _repository_path, _repository_server

        print "Try to push rpms to repository..."
        for file in rpm_files:
            local_file = file
            arch = platform.machine()
            cur_branch = branch
            if local_file.endswith(".src.rpm"):
                arch = "SRPMS"

            if local_file.find("-debuginfo-") > 0:
                cur_branch = "debuginfo"
            elif local_file.find("-debug-") > 0:
                cur_branch = "debuginfo"

            filename = os.path.basename(file)
            remote_file = "%s/%d/%s/packages/%s"%(_repository_path, osver, arch, filename)

            # check if file exists
            if is_file_exists(sftp_client, remote_file, opts.overwrite):
                raise DistPushError, "file %s exists in repository, please update the version"%(filename)

            # create the path if not exists
            create_sftp_dir(sftp_client, os.path.dirname(remote_file))

            # push file
            try :
                attr = sftp_client.put(local_file, remote_file)
            except Exception, e:
                raise DistPushError, "Push %s to repository failed!"%(local_file)
                
            # setup symlink
            try :
                # check all the branches 
                if opts.overwrite:
                    for b in branch_list:
                        file = "%s/%d/%s/%s/packages/%s"%(_repository_path, osver, arch, b, filename)
                        if is_file_exists(sftp_client, file, False):
                            sftp_client.remove(file)

                remote_branch_path = "%s/%d/%s/%s/packages/"%(_repository_path, osver, arch, cur_branch)
                create_sftp_symlink(sftp_client, remote_branch_path, filename, opts.overwrite)
                update_last_modify_time(sftp_client, osver, arch, cur_branch)
                print "Push %s done!"%(local_file)
            except IOError, e:
                raise DistExistsError, "Push %s to %s branch failed!"%(filename, cur_branch)



        return 0, ["All done!"]

class DistMoveCommand(YumCommand):
    def getNames(self):
        return ['dist-move', 'dist-mv']

    def getUsage(self):
        return ("PACKAGE...")

    def getSummary(self):
        return ("Move rpm file from one branch to another")

    def doCheck(self, base, basecmd, extcmds):
        pass

    def doCommand(self, base, basecmd, extcmds):
        opts = base.plugins.cmdline[0]

        print "================================\n"
        
        if len(base.plugins.cmdline[1]) <= 1:
            raise DistPushError, "Must specify at least one package to be move (i.e yum dist-move pkg)";

        # get the branch
        from_branch = None
        to_branch = None
        if opts.from_branch in branch_list:
            from_branch = opts.from_branch 
        if opts.to_branch in branch_list:
            to_branch = opts.to_branch

        if not from_branch:
            while from_branch not in branch_list:
                from_branch = raw_input("Please enter the old branch [test] : ")
                if from_branch == "":
                    from_branch = "test"

        if not to_branch:
            while to_branch not in branch_list:
                to_branch = raw_input("Please enter the new branch [current] : ")
                if to_branch == "":
                    to_branch = "current"

        osver = None
        if opts.osver:
            osver = int(opts.osver)
            if (osver < 6) or (osver > 10):
                raise DistPushError, "osver must be a number, and between 6 and 10"
        
        if not osver:
            osver = platform.dist()[1]
            osver = int(osver[0:osver.index(".")])

        # get the os arch
        arch = platform.machine()

        if opts.arch in arch_list:
            arch = opts.arch

        search_file = os.path.basename(base.plugins.cmdline[1][1])

        sftp_client = get_sftp_client()

        rpm_files = guess_rpm_files(sftp_client, osver, arch, from_branch, search_file)

        count = 0;
        rpm_file = None
        if rpm_files:
            while True:
                print "Which file do you want to move from %s branch to %s branch :\n"%(from_branch, to_branch)
                for i in range(len(rpm_files)):
                    print "    %d. %s\n"%(i + 1, rpm_files[i])

                idx = raw_input("Please enter the index or [n] for exit : ")
                if idx == 'n':
                    print "You select exit!"
                    break

                try :
                    idx = int(idx)
                except:
                    idx = -1

                to_move = False
                if idx > 0 and idx <= len(rpm_files):
                    to_move = True
                    rpm_file = rpm_files[idx - 1]

                if to_move:
                    to_path = "%s/%d/%s/%s/packages/"%(_repository_path, osver, arch, to_branch)
                    from_file = "%s/%d/%s/%s/packages/%s"%(_repository_path, osver, arch, from_branch, rpm_file)

                    sftp_client.remove(from_file)

                    count = count + 1
                    try :
                        create_sftp_symlink(sftp_client, to_path, rpm_file, opts.overwrite)
                        del rpm_files[idx - 1]
                        print "Move %s from %s branch to %s branch success!"%(rpm_file, from_branch, to_branch)
                    except IOError:
                        raise DistMoveError, "Move %s from %s branch to %s branch failed!"%(rpm_file, from_branch, to_branch)
        else:
            print "Cann't find package %s in %s branch"%(search_file, from_branch)

        if count > 0:
            update_last_modify_time(sftp_client, osver, arch, to_branch)
            update_last_modify_time(sftp_client, osver, arch, from_branch)

        return 0, [""]

class DistRemoveCommand(YumCommand):
    def getNames(self):
        return ['dist-remove', 'dist-rm']

    def getUsage(self):
        return ("PACKAGE...")

    def getSummary(self):
        return ("Remove rpm package from repository")

    def doCheck(self, base, basecmd, extcmds):
        pass

    def doCommand(self, base, basecmd, extcmds):
        print "Not implement!"
        return 0, [""]

def config_hook(conduit):
    parser = conduit.getOptParser()
    parser.add_option('', '--branch', dest='branch',
        default='', help="specify the branch")

    parser.add_option('', '--arch', dest='arch',
        default='', help="specify the arch")

    parser.add_option('', '--osver', dest='osver',
        default='', help="specify the os version: 6, 7")

    parser.add_option('', '--overwrite', dest='overwrite', action="store_true",
        default=False, help="overwrite the package")

    parser.add_option('', '--from-branch', dest='from_branch',
        default='', help="specify the from branch while moving rpm package")
    
    parser.add_option('', '--to-branch', dest='to_branch',
        default='', help="specify the to branch while moving rpm package")

    conduit.registerCommand(DistPushCommand())
    conduit.registerCommand(DistMoveCommand())
    conduit.registerCommand(DistRemoveCommand())

    global _repository_path, _repository_port, _repository_server, _identity_file, _repository_user

    _repository_prefix = conduit.confString("repository", "prefix", "dist")
    _repository_server = conduit.confString("repository", "server")
    _repository_path = conduit.confString("repository", "path")
    _repository_user = conduit.confString("repository", "user", "dist-user")
    _repository_port = conduit.confInt("repository", "port", 22)
    _identity_file = conduit.confString("repository", "identity_file")

    if not _repository_server or not _repository_path or not _identity_file:
        raise DistPushError, "Must specify repository_server, repository_path, identity_file"

def args_hook(conduit):
    optparser = conduit.getOptParser()
    (opts, cmds) = optparser.parse_args(args=conduit.getArgs())

    if opts.branch:
        conduit.getRepos().enableRepo("%s-%s"%(_repository_prefix, opts.branch))

