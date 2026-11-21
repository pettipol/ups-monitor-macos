/* SPDX-License-Identifier: GPL-2.0-or-later
 * Fake-only OS/serial/query seams for the portable continuous replay.
 * Sentinel bodies reused from test_hidapi_full_driver.c (pinned in manifest).
 * The fake chdir is a no-op: this closed dump-mode invocation needs no cwd.
 * This file is never linked into any production or genuine HID target.
 */
#include "config.h"
#include "common.h"
#include "serial.h"
#include "upsdrvquery.h"
#include <pwd.h>
#include <grp.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>

static void event(const char *text) { (void)text; }
static void forbidden(const char *name)
{
    fprintf(stderr, "FORBIDDEN:%s\n", name);
    fflush(stderr);
    _Exit(125);
}

/* No privilege lookup/change in the fake process. NUT parsing and the real
 * signal handler remain intact; only the external effects below are seams. */
struct passwd *fixture_get_user_pwent(const char *name)
{
	(void)name; event("USER_LOOKUP_SUPPRESSED"); return NULL;
}
void fixture_become_user(struct passwd *user) { (void)user; event("PRIVILEGE_SUPPRESSED"); }
void fixture_chroot_start(const char *path) { (void)path; forbidden("chroot_start"); }
void fixture_open_syslog(const char *name) { (void)name; event("SYSLOG_SUPPRESSED"); }
void fixture_writepid(const char *name) { (void)name; forbidden("writepid"); }
int fixture_chdir(const char *path)
{
	/* The closed dump invocation has no need to change directories. */
	(void)path; return 0;
}

pid_t fixture_os_fork(void) { forbidden("fork"); return -1; }
pid_t fixture_os_setsid(void) { forbidden("setsid"); return -1; }
int fixture_os_kill(pid_t pid, int sig) { (void)pid; (void)sig; forbidden("kill"); return -1; }
int fixture_os_socket(int domain, int type, int protocol)
{ (void)domain; (void)type; (void)protocol; forbidden("socket"); return -1; }
int fixture_os_connect(int fd, const struct sockaddr *address, socklen_t length)
{ (void)fd; (void)address; (void)length; forbidden("connect"); return -1; }
int fixture_os_bind(int fd, const struct sockaddr *address, socklen_t length)
{ (void)fd; (void)address; (void)length; forbidden("bind"); return -1; }
int fixture_os_listen(int fd, int backlog) { (void)fd; (void)backlog; forbidden("listen"); return -1; }
int fixture_os_accept(int fd, struct sockaddr *address, socklen_t *length)
{ (void)fd; (void)address; (void)length; forbidden("accept"); return -1; }
int fixture_os_getsockopt(int fd, int level, int name, void *value, socklen_t *length)
{ (void)fd; (void)level; (void)name; (void)value; (void)length; forbidden("getsockopt"); return -1; }
int fixture_os_pipe(int fds[2]) { (void)fds; forbidden("pipe"); return -1; }
int fixture_os_setuid(uid_t uid) { (void)uid; forbidden("setuid"); return -1; }
int fixture_os_setgid(gid_t gid) { (void)gid; forbidden("setgid"); return -1; }
int fixture_os_seteuid(uid_t uid) { (void)uid; forbidden("seteuid"); return -1; }
int fixture_os_setegid(gid_t gid) { (void)gid; forbidden("setegid"); return -1; }
int fixture_os_initgroups(const char *name, gid_t gid)
{ (void)name; (void)gid; forbidden("initgroups"); return -1; }
int fixture_os_chroot(const char *path) { (void)path; forbidden("chroot"); return -1; }
struct passwd *fixture_os_getpwnam(const char *name) { (void)name; forbidden("getpwnam"); return NULL; }
struct passwd *fixture_os_getpwuid(uid_t uid) { (void)uid; forbidden("getpwuid"); return NULL; }
struct group *fixture_os_getgrnam(const char *name) { (void)name; forbidden("getgrnam"); return NULL; }
int fixture_os_unlink(const char *path) { (void)path; forbidden("unlink"); return -1; }
int fixture_os_chmod(const char *path, mode_t mode)
{ (void)path; (void)mode; forbidden("chmod"); return -1; }
int fixture_os_fchmod(int fd, mode_t mode) { (void)fd; (void)mode; forbidden("fchmod"); return -1; }
int fixture_os_chown(const char *path, uid_t owner, gid_t group)
{ (void)path; (void)owner; (void)group; forbidden("chown"); return -1; }
int fixture_os_fchown(int fd, uid_t owner, gid_t group)
{ (void)fd; (void)owner; (void)group; forbidden("fchown"); return -1; }
void fixture_os_openlog(const char *ident, int option, int facility)
{ (void)ident; (void)option; (void)facility; forbidden("openlog"); }
void fixture_os_syslog(int priority, const char *format, ...)
{ (void)priority; (void)format; forbidden("syslog"); }

static void forbidden_serial(void) { forbidden("serial"); }
TYPE_FD_SER ser_open_nf(const char *port) { (void)port; forbidden_serial(); return (TYPE_FD_SER)-1; }
TYPE_FD_SER ser_open(const char *port) { (void)port; forbidden_serial(); return (TYPE_FD_SER)-1; }
int ser_set_speed(TYPE_FD_SER fd, const char *port, speed_t speed)
{ (void)fd; (void)port; (void)speed; forbidden_serial(); return -1; }
int ser_set_speed_nf(TYPE_FD_SER fd, const char *port, speed_t speed)
{ (void)fd; (void)port; (void)speed; forbidden_serial(); return -1; }
int ser_set_dtr(TYPE_FD_SER fd, int value) { (void)fd; (void)value; forbidden_serial(); return -1; }
int ser_set_rts(TYPE_FD_SER fd, int value) { (void)fd; (void)value; forbidden_serial(); return -1; }
int ser_close(TYPE_FD_SER fd, const char *port) { (void)fd; (void)port; forbidden_serial(); return -1; }
ssize_t ser_send_char(TYPE_FD_SER fd, unsigned char ch)
{ (void)fd; (void)ch; forbidden_serial(); return -1; }
ssize_t ser_send_buf(TYPE_FD_SER fd, const void *data, size_t count)
{ (void)fd; (void)data; (void)count; forbidden_serial(); return -1; }
ssize_t ser_send_buf_pace(TYPE_FD_SER fd, useconds_t delay, const void *data, size_t count)
{ (void)fd; (void)delay; (void)data; (void)count; forbidden_serial(); return -1; }
ssize_t ser_get_char(TYPE_FD_SER fd, void *data, time_t seconds, useconds_t microseconds)
{ (void)fd; (void)data; (void)seconds; (void)microseconds; forbidden_serial(); return -1; }
int ser_flush_io(TYPE_FD_SER fd) { (void)fd; forbidden_serial(); return -1; }
void ser_comm_fail(const char *format, ...) { (void)format; }
void ser_comm_good(void) { }
int nut_upsdrvquery_debug_level = NUT_UPSDRVQUERY_DEBUG_LEVEL_DEFAULT;
ssize_t upsdrvquery_oneshot(const char *driver, const char *ups, const char *query,
	char *buffer, const size_t capacity, struct timeval *timeout)
{
	(void)driver; (void)ups; (void)query; (void)buffer; (void)capacity; (void)timeout;
	forbidden("peer_query"); return -1;
}


