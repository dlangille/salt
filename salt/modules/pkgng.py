# -*- coding: utf-8 -*-
'''
Support for ``pkgng``, the new package manager for FreeBSD

.. warning::

    This module has been completely rewritten. Up to and includng version
    0.17.0, it was available as the ``pkgng`` module, (``pkgng.install``,
    ``pkgng.delete``, etc.), but moving forward this module will no longer be
    available as ``pkgng``, as it will behave like a normal Salt ``pkg``
    provider. The documentation below should not be considered to apply to this
    module in versions <= 0.17.0. If your minion is running one of these
    versions, then the documentation for this module can be viewed using the
    :mod:`sys.doc <salt.modules.sys.doc>` function:

    .. code-block:: bash

        salt bsdminion sys.doc pkgng


This module provides an interface to ``pkg(8)``. It acts as the default
package provider for FreeBSD 10 and newer. For FreeBSD hosts which have
been upgraded to use pkgng, you will need to override the ``pkg`` provider
by setting the :conf_minion:`providers` parameter in your Minion config
file, in order to use this module to manage packages, like so:

.. code-block:: yaml

    providers:
      pkg: pkgng

'''

# Import python libs
import copy
import logging
import os

# Import salt libs
import salt.utils

log = logging.getLogger(__name__)

# Define the module's virtual name
__virtualname__ = 'pkg'


def __virtual__():
    '''
    Load as 'pkg' on FreeBSD 10 and greater
    '''
    if __grains__['os'] == 'FreeBSD' and float(__grains__['osrelease']) >= 10:
        return __virtualname__
    return False


def _pkg(jail=None, chroot=None):
    '''
    Returns the prefix for a pkg command, using -j if a jail is specified, or
    -c if chroot is specified.
    '''
    ret = 'pkg'
    if jail:
        ret += ' -j {0!r}'.format(jail)
    elif chroot:
        ret += ' -c {0!r}'.format(chroot)
    return ret


def _get_version(name, results):
    '''
    ``pkg search`` will return all packages for which the pattern is a match.
    Narrow this down and return the package version, or None if no exact match.
    '''
    for line in results.splitlines():
        if not line:
            continue
        try:
            pkgname, pkgver = line.rsplit('-', 1)
        except ValueError:
            continue
        if pkgname == name:
            return pkgver
    return None


def _contextkey(jail=None, chroot=None):
    '''
    As this module is designed to manipulate packages in jails and chroots, use
    the passed jail/chroot to ensure that a key in the __context__ dict that is
    unique to that jail/chroot is used.
    '''
    ret = 'pkg.list_pkgs'
    if jail:
        ret += '.jail_{0}'.format(jail)
    elif chroot:
        ret += '.chroot_{0}'.format(chroot)
    return ret


def parse_config(file_name='/usr/local/etc/pkg.conf'):
    '''
    Return dict of uncommented global variables.

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.parse_config

    ``NOTE:`` not working properly right now
    '''
    ret = {}
    if not os.path.isfile(file_name):
        return 'Unable to find {0} on file system'.format(file_name)

    with salt.utils.fopen(file_name) as ifile:
        for line in ifile:
            if line.startswith('#') or line.startswith('\n'):
                pass
            else:
                key, value = line.split('\t')
                ret[key] = value
    ret['config_file'] = file_name
    return ret


def version(*names, **kwargs):
    '''
    Returns a string representing the package version or an empty string if not
    installed. If more than one package name is specified, a dict of
    name/version pairs is returned.

    .. note::

        This function can accessed using ``pkg.info`` in addition to
        ``pkg.version``, to more closely match the CLI usage of ``pkg(8)``.

    jail
        Get package version information for the specified jail

    chroot
        Get package version information for the specified chroot (ignored if
        ``jail`` is specified)


    CLI Example:

    .. code-block:: bash

        salt '*' pkg.version <package name>
        salt '*' pkg.version <package name> jail=<jail name or id>
        salt '*' pkg.version <package1> <package2> <package3> ...
    '''
    return __salt__['pkg_resource.version'](*names, **kwargs)

# Support pkg.info get version info, since this is the CLI usage
info = version


def refresh_db(jail=None, chroot=None, force=False):
    '''
    Refresh PACKAGESITE contents

    .. note::

        This function can accessed using ``pkg.update`` in addition to
        ``pkg.refresh_db``, to more closely match the CLI usage of ``pkg(8)``.

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.refresh_db

    jail
        Refresh the pkg database within the specified jail

    chroot
        Refresh the pkg database within the specified chroot (ignored if
        ``jail`` is specified)

    force
        Force a full download of the repository catalogue without regard to the
        respective ages of the local and remote copies of the catalogue.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.refresh_db force=True
    '''
    opts = ''
    if force:
        opts += ' -f'
    return __salt__['cmd.retcode'](
        '{0} update{1}'.format(_pkg(jail, chroot), opts)) == 0


# Support pkg.update to refresh the db, since this is the CLI usage
update = refresh_db


def latest_version(*names, **kwargs):
    '''
    Return the latest version of the named package available for upgrade or
    installation. If more than one package name is specified, a dict of
    name/version pairs is returned.

    If the latest version of a given package is already installed, an empty
    string will be returned for that package.

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.latest_version <package name>
        salt '*' pkg.latest_version <package name> jail=<jail name or id>
        salt '*' pkg.latest_version <package name> chroot=/path/to/chroot
    '''
    if len(names) == 0:
        return ''
    ret = {}
    # Initialize the dict with empty strings
    for name in names:
        ret[name] = ''
    jail = kwargs.get('jail')
    chroot = kwargs.get('chroot')
    pkgs = list_pkgs(versions_as_list=True, jail=jail, chroot=chroot)

    for name in names:
        cmd = '{0} search {1}'.format(_pkg(jail, chroot), name)
        pkgver = _get_version(name, __salt__['cmd.run'](cmd))
        if pkgver is not None:
            installed = pkgs.get(name, [])
            if not installed:
                ret[name] = pkgver
            else:
                if not any(
                    (salt.utils.compare_versions(ver1=x,
                                                 oper='>=',
                                                 ver2=pkgver)
                     for x in installed)
                ):
                    ret[name] = pkgver

    # Return a string if only one package name passed
    if len(names) == 1:
        return ret[names[0]]
    return ret


# available_version is being deprecated
available_version = latest_version


def list_pkgs(versions_as_list=False, jail=None, chroot=None, **kwargs):
    '''
    List the packages currently installed as a dict::

        {'<package_name>': '<version>'}

    jail
        List the packages in the specified jail

    chroot
        List the pacakges in the specified chroot (ignored if ``jail`` is
        specified)

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.list_pkgs
        salt '*' pkg.list_pkgs jail=<jail name or id>
        salt '*' pkg.list_pkgs chroot=/path/to/chroot
    '''
    # 'removed' not applicable
    if salt.utils.is_true(kwargs.get('removed')):
        return {}

    versions_as_list = salt.utils.is_true(versions_as_list)
    contextkey = _contextkey(jail, chroot)

    if contextkey in __context__:
        if versions_as_list:
            return __context__[contextkey]
        else:
            ret = copy.deepcopy(__context__[contextkey])
            __salt__['pkg_resource.stringify'](ret)
            return ret

    ret = {}
    cmd = '{0} info'.format(_pkg(jail, chroot))
    for line in __salt__['cmd.run_stdout'](cmd).splitlines():
        if not line:
            continue
        try:
            pkg, ver = line.split()[0].rsplit('-', 1)
        except (IndexError, ValueError):
            continue
        __salt__['pkg_resource.add_pkg'](ret, pkg, ver)

    __salt__['pkg_resource.sort_pkglist'](ret)
    __context__[contextkey] = copy.deepcopy(ret)
    if not versions_as_list:
        __salt__['pkg_resource.stringify'](ret)
    return ret


def update_package_site(new_url):
    '''
    Updates remote package repo URL, PACKAGESITE var to be exact.

    Must use ``http://``, ``ftp://``, or ``https://`` protocol

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.update_package_site http://127.0.0.1/
    '''
    config_file = parse_config()['config_file']
    __salt__['file.sed'](
        config_file, 'PACKAGESITE.*', 'PACKAGESITE\t : {0}'.format(new_url)
    )

    # add change return later
    return True


def stats(local=False, remote=False, jail=None, chroot=None):
    '''
    Return pkgng stats.

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.stats

    local
        Display stats only for the local package database.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.stats local=True

    remote
        Display stats only for the remote package database(s).

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.stats remote=True

    jail
        Retrieve stats from the specified jail.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.stats jail=<jail name or id>
            salt '*' pkg.stats jail=<jail name or id> local=True
            salt '*' pkg.stats jail=<jail name or id> remote=True

    chroot
        Retrieve stats from the specified chroot (ignored if ``jail`` is
        specified).

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.stats chroot=/path/to/chroot
            salt '*' pkg.stats chroot=/path/to/chroot local=True
            salt '*' pkg.stats chroot=/path/to/chroot remote=True
    '''

    opts = ''
    if local:
        opts += 'l'
    if remote:
        opts += 'r'
    if opts:
        opts = '-' + opts

    res = __salt__['cmd.run'](
        '{0} stats {1}'.format(_pkg(jail, chroot), opts)
    )
    res = [x.strip("\t") for x in res.split("\n")]
    return res


def backup(file_name, jail=None, chroot=None):
    '''
    Export installed packages into yaml+mtree file

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.backup /tmp/pkg

    jail
        Backup packages from the specified jail. Note that this will run the
        command within the jail, and so the path to the backup file will be
        relative to the root of the jail

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.backup /tmp/pkg jail=<jail name or id>

    chroot
        Backup packages from the specified chroot (ignored if ``jail`` is
        specified). Note that this will run the command within the chroot, and
        so the path to the backup file will be relative to the root of the
        chroot.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.backup /tmp/pkg chroot=/path/to/chroot
    '''
    res = __salt__['cmd.run'](
        '{0} backup -d {1!r}'.format(_pkg(jail, chroot), file_name)
    )
    return res.split('...')[1]


def restore(file_name, jail=None, chroot=None):
    '''
    Reads archive created by pkg backup -d and recreates the database.

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.restore /tmp/pkg

    jail
        Restore database to the specified jail. Note that this will run the
        command within the jail, and so the path to the file from which the pkg
        database will be restored is relative to the root of the jail.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.restore /tmp/pkg jail=<jail name or id>

    chroot
        Restore database to the specified chroot (ignored if ``jail`` is
        specified). Note that this will run the command within the chroot, and
        so the path to the file from which the pkg database will be restored is
        relative to the root of the chroot.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.restore /tmp/pkg chroot=/path/to/chroot
    '''
    return __salt__['cmd.run'](
        '{0} backup -r {0!r}'.format(_pkg(jail, chroot), file_name)
    )


def audit(jail=None, chroot=None):
    '''
    Audits installed packages against known vulnerabilities

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.audit

    jail
        Audit packages within the specified jail

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.audit jail=<jail name or id>

    chroot
        Audit packages within the specified chroot (ignored if ``jail`` is
        specified)

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.audit chroot=/path/to/chroot
    '''
    return __salt__['cmd.run']('{0} audit -F'.format(_pkg(jail, chroot)))


def install(name=None,
            fromrepo=None,
            pkgs=None,
            sources=None,
            jail=None,
            chroot=None,
            orphan=False,
            force=False,
            glob=False,
            local=False,
            dryrun=False,
            quiet=False,
            require=False,
            regex=False,
            pcre=False,
            **kwargs):
    '''
    Install package(s) from a repository

    name
        The name of the package to install

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.install <package name>

    jail
        Install the package into the specified jail

    chroot
        Install the paackage into the specified chroot (ignored if ``jail`` is
        specified)

    orphan
        Mark the installed package as orphan. Will be automatically removed
        if no other packages depend on them. For more information please
        refer to ``pkg-autoremove(8)``.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.install <package name> orphan=True

    force
        Force the reinstallation of the package if already installed.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.install <package name> force=True

    glob
        Treat the package names as shell glob patterns.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.install <package name> glob=True

    local
        Do not update the repository catalogues with ``pkg-update(8)``.  A
        value of ``True`` here is equivalent to using the ``-U`` flag with
        ``pkg install``.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.install <package name> local=True

    dryrun
        Dru-run mode. The list of changes to packages is always printed,
        but no changes are actually made.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.install <package name> dryrun=True

    quiet
        Force quiet output, except when dryrun is used, where pkg install
        will always show packages to be installed, upgraded or deleted.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.install <package name> quiet=True

    require
        When used with force, reinstalls any packages that require the
        given package.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.install <package name> require=True force=True

    fromrepo
        In multi-repo mode, override the pkg.conf ordering and only attempt
        to download packages from the named repository.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.install <package name> fromrepo=repo

    regex
        Treat the package names as a regular expression

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.install <regular expression> regex=True

    pcre
        Treat the package names as extended regular expressions.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.install <extended regular expression> pcre=True
    '''
    pkg_params, pkg_type = __salt__['pkg_resource.parse_targets'](name,
                                                                  pkgs,
                                                                  sources,
                                                                  **kwargs)

    if pkg_params is None or len(pkg_params) == 0:
        return {}

    opts = ''
    repo_opts = ''
    if salt.utils.is_true(orphan):
        opts += 'A'
    if salt.utils.is_true(force):
        opts += 'f'
    if salt.utils.is_true(glob):
        opts += 'g'
    if salt.utils.is_true(local):
        opts += 'U'
    if salt.utils.is_true(dryrun):
        opts += 'n'
    if not salt.utils.is_true(dryrun):
        opts += 'y'
    if salt.utils.is_true(quiet):
        opts += 'q'
    if salt.utils.is_true(require):
        opts += 'R'
    if salt.utils.is_true(fromrepo):
        repo_opts += 'r {0}'.format(fromrepo)
    if salt.utils.is_true(regex):
        opts += 'x'
    if salt.utils.is_true(pcre):
        opts += 'X'
    if opts:
        opts = '-' + opts
    if repo_opts:
        repo_opts = '-' + repo_opts

    old = list_pkgs(jail=jail, chroot=chroot)

    if pkg_type == 'file':
        pkg_cmd = 'add'
        targets = pkg_params.keys()
    elif pkg_type == 'repository':
        pkg_cmd = 'install'
        if pkgs is None and kwargs.get('version') and len(pkg_params) == 1:
            # Only use the 'version' param if 'name' was not specified as a
            # comma-separated list
            pkg_params = {name: kwargs.get('version')}
        targets = []
        for param, version_num in pkg_params.iteritems():
            if version_num is None:
                targets.append(param)
            else:
                targets.append('{0}-{1}'.format(param, version_num))

    cmd = '{0} {1} {2} {3} {4}'.format(
        _pkg(jail, chroot), pkg_cmd, repo_opts, opts, ' '.join(targets)
    )
    __salt__['cmd.run_all'](cmd)
    __context__.pop(_contextkey(jail, chroot), None)
    new = list_pkgs(jail=jail, chroot=chroot)
    return salt.utils.compare_dicts(old, new)


def remove(name=None,
           pkgs=None,
           jail=None,
           chroot=None,
           all_installed=False,
           force=False,
           glob=False,
           dryrun=False,
           recurse=False,
           regex=False,
           pcre=False,
           **kwargs):
    '''
    Remove a package from the database and system

    .. note::

        This function can accessed using ``pkg.delete`` in addition to
        ``pkg.remove``, to more closely match the CLI usage of ``pkg(8)``.

    name
        The package to remove

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.remove <package name>

    jail
        Delete the package from the specified jail

    chroot
        Delete the paackage grom the specified chroot (ignored if ``jail`` is
        specified)

    all_installed
        Deletes all installed packages from the system and empties the
        database. USE WITH CAUTION!

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.remove all all_installed=True force=True

    force
        Forces packages to be removed despite leaving unresolved
        dependencies.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.remove <package name> force=True

    glob
        Treat the package names as shell glob patterns.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.remove <package name> glob=True

    dryrun
        Dry run mode. The list of packages to delete is always printed, but
        no packages are actually deleted.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.remove <package name> dryrun=True

    recurse
        Delete all packages that require the listed package as well.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.remove <package name> recurse=True

    regex
        Treat the package names as regular expressions.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.remove <regular expression> regex=True

    pcre
        Treat the package names as extended regular expressions.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.remove <extended regular expression> pcre=True
    '''
    pkg_params = __salt__['pkg_resource.parse_targets'](name, pkgs)[0]
    old = list_pkgs(jail=jail, chroot=chroot)
    targets = [x for x in pkg_params if x in old]
    if not targets:
        return {}

    opts = ''
    if salt.utils.is_true(all_installed):
        opts += 'a'
    if salt.utils.is_true(force):
        opts += 'f'
    if salt.utils.is_true(glob):
        opts += 'g'
    if salt.utils.is_true(dryrun):
        opts += 'n'
    if not salt.utils.is_true(dryrun):
        opts += 'y'
    if salt.utils.is_true(recurse):
        opts += 'R'
    if salt.utils.is_true(regex):
        opts += 'x'
    if salt.utils.is_true(pcre):
        opts += 'X'
    if opts:
        opts = '-' + opts

    cmd = '{0} delete {1} {2}'.format(
        _pkg(jail, chroot), opts, ' '.join(targets)
    )
    __salt__['cmd.run_all'](cmd)
    __context__.pop(_contextkey(jail, chroot), None)
    new = list_pkgs(jail=jail, chroot=chroot)
    return salt.utils.compare_dicts(old, new)

# Support pkg.delete to remove packages, since this is the CLI usage
delete = remove
# No equivalent to purge packages, use remove instead
purge = remove


def upgrade(jail=None, chroot=None, force=False, local=False, dryrun=False):
    '''
    Upgrade all packages (run a ``pkg upgrade``)

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.upgrade

    jail
        Audit packages within the specified jail

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.upgrade jail=<jail name or id>

    chroot
        Audit packages within the specified chroot (ignored if ``jail`` is
        specified)

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.upgrade chroot=/path/to/chroot


    Any of the below options can also be used with ``jail`` or ``chroot``.

    force
        Force reinstalling/upgrading the whole set of packages.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.upgrade force=True

    local
        Do not update the repository catalogues with ``pkg-update(8)``. A value
        of ``True`` here is equivalent to using the ``-U`` flag with ``pkg
        upgrade``.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.upgrade local=True

    dryrun
        Dry-run mode: show what packages have updates available, but do not
        perform any upgrades. Repository catalogues will be updated as usual
        unless the local option is also given.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.upgrade dryrun=True
    '''
    opts = ''
    if force:
        opts += 'f'
    if local:
        opts += 'L'
    if dryrun:
        opts += 'n'
    if not dryrun:
        opts += 'y'
    if opts:
        opts = '-' + opts

    return __salt__['cmd.run'](
        '{0} upgrade {1}'.format(_pkg(jail, chroot), opts)
    )


def clean(jail=None, chroot=None):
    '''
    Cleans the local cache of fetched remote packages

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.clean
        salt '*' pkg.clean jail=<jail name or id>
        salt '*' pkg.clean chroot=/path/to/chroot
    '''
    return __salt__['cmd.run']('{0} clean'.format(_pkg(jail, chroot)))


def autoremove(jail=None, chroot=None, dryrun=False):
    '''
    Delete packages which were automatically installed as dependencies and are
    not required anymore.

    dryrun
        Dry-run mode. The list of changes to packages is always printed,
        but no changes are actually made.

    CLI Example:

    .. code-block:: bash

         salt '*' pkg.autoremove
         salt '*' pkg.autoremove jail=<jail name or id>
         salt '*' pkg.autoremove dryrun=True
         salt '*' pkg.autoremove jail=<jail name or id> dryrun=True
    '''
    opts = ''
    if dryrun:
        opts += 'n'
    else:
        opts += 'y'
    if opts:
        opts = '-' + opts
    return __salt__['cmd.run'](
        '{0} autoremove {1}'.format(_pkg(jail, chroot), opts)
    )


def check(jail=None,
          chroot=None,
          depends=False,
          recompute=False,
          checksum=False):
    '''
    Sanity checks installed packages

    jail
        Perform the sanity check in the specified jail

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.check jail=<jail name or id>

    chroot
        Perform the sanity check in the specified chroot (ignored if ``jail``
        is specified)

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.check chroot=/path/to/chroot


    Of the below, at least one must be set to ``True``.

    depends
        Check for and install missing dependencies.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.check recompute=True

    recompute
        Recompute sizes and checksums of installed packages.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.check depends=True

    checksum
        Find invalid checksums for installed packages.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.check checksum=True
    '''
    if not any((depends, recompute, checksum)):
        return 'One of depends, recompute, or checksum must be set to True'

    opts = ''
    if depends:
        opts += 'dy'
    if recompute:
        opts += 'r'
    if checksum:
        opts += 's'
    if opts:
        opts = '-' + opts

    return __salt__['cmd.run'](
        '{0} check {1}'.format(_pkg(jail, chroot), opts)
    )


def which(path, jail=None, chroot=None, origin=False, quiet=False):
    '''
    Displays which package installed a specific file

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.which <file name>

    jail
        Perform the check in the specified jail

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.which <file name> jail=<jail name or id>

    chroot
        Perform the check in the specified chroot (ignored if ``jail`` is
        specified)

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.which <file name> chroot=/path/to/chroot


    origin
        Shows the origin of the package instead of name-version.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.which <file name> origin=True

    quiet
        Quiet output.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.which <file name> quiet=True
    '''
    opts = ''
    if quiet:
        opts += 'q'
    if origin:
        opts += 'o'
    if opts:
        opts = '-' + opts
    return __salt__['cmd.run'](
        '{0} which {1} {2}'.format(_pkg(jail, chroot), opts, path))


def search(name,
           jail=None,
           chroot=None,
           exact=False,
           glob=False,
           regex=False,
           pcre=False,
           comment=False,
           desc=False,
           full=False,
           depends=False,
           size=False,
           quiet=False,
           origin=False,
           prefix=False):
    '''
    Searches in remote package repositories

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.search pattern

    jail
        Perform the search using the ``pkg.conf(5)`` from the specified jail

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.search pattern jail=<jail name or id>

    chroot
        Perform the search using the ``pkg.conf(5)`` from the specified chroot
        (ignored if ``jail`` is specified)

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.search pattern chroot=/path/to/chroot

    exact
        Treat pattern as exact pattern.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.search pattern exact=True

    glob
        Treat pattern as a shell glob pattern.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.search pattern glob=True

    regex
        Treat pattern as a regular expression.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.search pattern regex=True

    pcre
        Treat pattern as an extended regular expression.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.search pattern pcre=True

    comment
        Search for pattern in the package comment one-line description.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.search pattern comment=True

    desc
        Search for pattern in the package description.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.search pattern desc=True

    full
        Displays full information about the matching packages.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.search pattern full=True

    depends
        Displays the dependencies of pattern.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.search pattern depends=True

    size
        Displays the size of the package

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.search pattern size=True

    quiet
        Be quiet. Prints only the requested information without displaying
        many hints.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.search pattern quiet=True

    origin
        Displays pattern origin.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.search pattern origin=True

    prefix
        Displays the installation prefix for each package matching pattern.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.search pattern prefix=True
    '''

    opts = ''
    if exact:
        opts += 'e'
    if glob:
        opts += 'g'
    if regex:
        opts += 'x'
    if pcre:
        opts += 'X'
    if comment:
        opts += 'c'
    if desc:
        opts += 'D'
    if full:
        opts += 'f'
    if depends:
        opts += 'd'
    if size:
        opts += 's'
    if quiet:
        opts += 'q'
    if origin:
        opts += 'o'
    if prefix:
        opts += 'p'
    if opts:
        opts = '-' + opts

    return __salt__['cmd.run'](
        '{0} search {1} {2}'.format(_pkg(jail, chroot), opts, name)
    )


def fetch(name,
          jail=None,
          chroot=None,
          fetch_all=False,
          quiet=False,
          fromrepo=None,
          glob=True,
          regex=False,
          pcre=False,
          local=False,
          depends=False):
    '''
    Fetches remote packages

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.fetch <package name>

    jail
        Fetch package in the specified jail

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.fetch <package name> jail=<jail name or id>

    chroot
        Fetch package in the specified chroot (ignored if ``jail`` is
        specified)

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.fetch <package name> chroot=/path/to/chroot

    fetch_all
        Fetch all packages.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.fetch <package name> fetch_all=True

    quiet
        Quiet mode. Show less output.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.fetch <package name> quiet=True

    fromrepo
        Fetches packages from the given repo if multiple repo support
        is enabled. See ``pkg.conf(5)``.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.fetch <package name> fromrepo=repo

    glob
        Treat pkg_name as a shell glob pattern.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.fetch <package name> glob=True

    regex
        Treat pkg_name as a regular expression.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.fetch <regular expression> regex=True

    pcre
        Treat pkg_name is an extended regular expression.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.fetch <extended regular expression> pcre=True

    local
        Skip updating the repository catalogues with pkg-update(8). Use the
        local cache only.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.fetch <package name> local=True

    depends
        Fetch the package and its dependencies as well.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.fetch <package name> depends=True
    '''
    opts = ''
    repo_opts = ''
    if fetch_all:
        opts += 'a'
    if quiet:
        opts += 'q'
    if fromrepo:
        repo_opts += 'r {0}'.format(fromrepo)
    if glob:
        opts += 'g'
    if regex:
        opts += 'x'
    if pcre:
        opts += 'X'
    if local:
        opts += 'L'
    if depends:
        opts += 'd'
    if opts:
        opts = '-' + opts
    if repo_opts:
        opts = '-' + repo_opts

    return __salt__['cmd.run'](
        '{0} fetch -y {1} {2} {3}'.format(
            _pkg(jail, chroot), repo_opts, opts, name
        )
    )


def updating(name,
             jail=None,
             chroot=None,
             filedate=None,
             filename=None):
    ''''
    Displays UPDATING entries of software packages

    CLI Example:

    .. code-block:: bash

        salt '*' pkg.updating foo

    jail
        Perform the action in the specified jail

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.updating foo jail=<jail name or id>

    chroot
        Perform the action in the specified chroot (ignored if ``jail`` is
        specified)

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.updating foo chroot=/path/to/chroot

    filedate
        Only entries newer than date are shown. Use a YYYYMMDD date format.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.updating foo filedate=20130101

    filename
        Defines an alternative location of the UPDATING file.

        CLI Example:

        .. code-block:: bash

            salt '*' pkg.updating foo filename=/tmp/UPDATING
    '''

    opts = ''
    if filedate:
        opts += 'd {0}'.format(filedate)
    if filename:
        opts += 'f {0}'.format(filename)
    if opts:
        opts = '-' + opts

    return __salt__['cmd.run'](
        '{0} updating {1} {2}'.format(_pkg(jail, chroot), opts, name)
    )
