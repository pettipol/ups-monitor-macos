/* SPDX-License-Identifier: GPL-2.0-or-later
 * Test-only redirection AFTER system declarations, never installed or active
 * in a production target. The final symbol audit is mandatory before spawn.
 */
#ifndef TEST_HIDAPI_FULL_OS_H
#define TEST_HIDAPI_FULL_OS_H
#include "config.h"
#include "common.h"
#include <sys/types.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>
#include <pwd.h>
#include <grp.h>
#include <syslog.h>

pid_t fixture_os_fork(void);
pid_t fixture_os_setsid(void);
int fixture_os_kill(pid_t pid, int sig);
int fixture_os_socket(int domain, int type, int protocol);
int fixture_os_connect(int fd, const struct sockaddr *address, socklen_t length);
int fixture_os_bind(int fd, const struct sockaddr *address, socklen_t length);
int fixture_os_listen(int fd, int backlog);
int fixture_os_accept(int fd, struct sockaddr *address, socklen_t *length);
int fixture_os_getsockopt(int fd, int level, int name, void *value, socklen_t *length);
int fixture_os_pipe(int fds[2]);
int fixture_os_setuid(uid_t uid);
int fixture_os_setgid(gid_t gid);
int fixture_os_seteuid(uid_t uid);
int fixture_os_setegid(gid_t gid);
int fixture_os_initgroups(const char *name, gid_t gid);
int fixture_os_chroot(const char *path);
struct passwd *fixture_os_getpwnam(const char *name);
struct passwd *fixture_os_getpwuid(uid_t uid);
struct group *fixture_os_getgrnam(const char *name);
int fixture_os_unlink(const char *path);
int fixture_os_chmod(const char *path, mode_t mode);
int fixture_os_fchmod(int fd, mode_t mode);
int fixture_os_chown(const char *path, uid_t owner, gid_t group);
int fixture_os_fchown(int fd, uid_t owner, gid_t group);
void fixture_os_openlog(const char *ident, int option, int facility);
void fixture_os_syslog(int priority, const char *format, ...);

#ifdef FULL_FAKE_MAIN
struct passwd *fixture_get_user_pwent(const char *name);
void fixture_become_user(struct passwd *user);
void fixture_chroot_start(const char *path);
void fixture_open_syslog(const char *name);
void fixture_writepid(const char *name);
int fixture_chdir(const char *path);
#define get_user_pwent fixture_get_user_pwent
#define become_user fixture_become_user
#define chroot_start fixture_chroot_start
#define open_syslog fixture_open_syslog
#define writepid fixture_writepid
#define chdir fixture_chdir
#endif

#define fork fixture_os_fork
#define setsid fixture_os_setsid
#define kill fixture_os_kill
#define socket fixture_os_socket
#define connect fixture_os_connect
#define bind fixture_os_bind
#define listen fixture_os_listen
#define accept fixture_os_accept
#define getsockopt fixture_os_getsockopt
#define pipe fixture_os_pipe
#define setuid fixture_os_setuid
#define setgid fixture_os_setgid
#define seteuid fixture_os_seteuid
#define setegid fixture_os_setegid
#define initgroups fixture_os_initgroups
#define chroot fixture_os_chroot
#define getpwnam fixture_os_getpwnam
#define getpwuid fixture_os_getpwuid
#define getgrnam fixture_os_getgrnam
#define unlink fixture_os_unlink
#define chmod fixture_os_chmod
#define fchmod fixture_os_fchmod
#define chown fixture_os_chown
#define fchown fixture_os_fchown
#define openlog fixture_os_openlog
#define syslog fixture_os_syslog
#endif
