/* SPDX-License-Identifier: GPL-2.0-or-later
 * Closed-entry wrapper for whole NUT main/APC/dstate with fake HIDAPI only.
 * Privilege/user operations and dangerous OS calls are explicit test seams.
 */
#include "config.h"
#include "common.h"
#include "main.h"
#include "serial.h"
#include "upsdrvquery.h"
#include "apcmicrolink.h"
#include "apcmicrolink-hidapi-session.h"
#include "test_hidapi_full_frames.h"
#include <hidapi.h>
#include <hidapi_darwin.h>
#include <fcntl.h>
#include <grp.h>
#include <limits.h>
#include <pwd.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <syslog.h>
#include <unistd.h>

int nut_real_main(int argc, char **argv);
void fixture_real_updateinfo(void);
void fixture_real_cleanup(void);
void fixture_real_dump(void);
void fixture_real_dataok(void);

static const char *scenario;
static FILE *events;
static char state_directory[PATH_MAX];
static unsigned int event_count, updates, dumps, cleanups, dataok;
static unsigned int inits, enumerations, opens, descriptors, reads, writes, closes, exits;
static unsigned int stop_writes, init_writes, next_writes;
static int exclusive = 1, report_queued, protocol_initialized, signal_sent;
static int64_t native_ms = 1000;
static enum fixture_frame_kind frame_kind = FIXTURE_METRICS;
struct hid_device_ { int synthetic; };
static struct hid_device_ device = {1};
static struct hid_device_info info;
static const unsigned char hid_descriptor[] = {
	0x06,0x86,0xff,0x09,0x01,0xa1,0x01,
	0x85,0x07,0x09,0xfd,0x75,0x08,0x95,0x3f,0x81,0x02,
	0x85,0x08,0x09,0xfc,0x75,0x08,0x95,0x3f,0x91,0x02,0xc0
};

static void event(const char *text)
{
	if (events == NULL || ++event_count > 512U || strlen(text) > 128U
	 || fprintf(events, "%s\n", text) < 0 || fflush(events)) _Exit(126);
}
static void count_event(const char *name, unsigned int count)
{
	char text[128];
	if (snprintf(text, sizeof(text), "%s=%u", name, count) >= (int)sizeof(text)) _Exit(126);
	event(text);
}
static void forbidden(const char *name)
{
	char text[128];
	if (snprintf(text, sizeof(text), "FORBIDDEN:%s", name) >= (int)sizeof(text)) _Exit(126);
	event(text);
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
	char resolved[PATH_MAX];
	if (!path || !realpath(path, resolved) || strcmp(resolved, state_directory)) forbidden("chdir");
	return chdir(state_directory);
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

void upsdrv_updateinfo(void)
{
	count_event("UPDATE", ++updates);
	fixture_real_updateinfo();
}
void upsdrv_cleanup(void)
{
	count_event("CLEANUP_ENTER", ++cleanups);
	fixture_real_cleanup();
	event("CLEANUP_RETURN");
}
void dstate_dump(void)
{
	count_event("DUMP_ENTER", ++dumps);
	fixture_real_dump();
	event("DUMP_RETURN");
}
void dstate_dataok(void)
{
	count_event("DATAOK", ++dataok);
	fixture_real_dataok();
}

int hid_init(void) { count_event("HID_INIT", ++inits); return 0; }
int hid_exit(void) { count_event("HID_EXIT", ++exits); return 0; }
void hid_darwin_set_open_exclusive(int value) { exclusive = value; event("NONEXCLUSIVE"); }
int hid_darwin_get_open_exclusive(void) { return exclusive; }
int hid_darwin_is_device_open_exclusive(hid_device *handle)
{ return handle == &device ? 0 : 1; }
struct hid_device_info *hid_enumerate(unsigned short vid, unsigned short pid)
{
	count_event("ENUMERATE", ++enumerations);
	if (vid != 0x1234 || pid != 0x5678) forbidden("fake_identity");
	return &info;
}
void hid_free_enumeration(struct hid_device_info *list)
{ if (list != &info) forbidden("fake_enumeration"); event("ENUM_FREE"); }
hid_device *hid_open_path(const char *path)
{
	if (!path || strcmp(path, "synthetic-full-nut")) forbidden("fake_path");
	count_event("HID_OPEN", ++opens); return &device;
}
int hid_get_report_descriptor(hid_device *handle, unsigned char *out, size_t capacity)
{
	size_t size = sizeof(hid_descriptor) - (!strcmp(scenario, "invalid-hid-descriptor") ? 1U : 0U);
	if (handle != &device || capacity < size) forbidden("fake_descriptor");
	count_event("HID_LAYOUT", ++descriptors);
	memcpy(out, hid_descriptor, size); return (int)size;
}
int hid_write(hid_device *handle, const unsigned char *data, size_t length)
{
	if (handle != &device || length != 64 || data[0] != 8 || !descriptors)
		forbidden("fake_write_framing");
	for (size_t i = 2; i < 64; i++) if (data[i] != 0) forbidden("noncontrol_write");
	writes++;
	if (data[1] == 0xf7) count_event("STOP", ++stop_writes);
	else if (data[1] == 0xfd) {
		count_event("INIT", ++init_writes);
		protocol_initialized = 1; report_queued = 1;
		if (!strcmp(scenario, "expiry-after-init")) native_ms = 21000;
	} else if (data[1] == 0xfe) {
		count_event("NEXT", ++next_writes);
		if (!strcmp(scenario, "metrics-dump")) report_queued = 1;
	} else forbidden("control_allowlist");
	return 64;
}
int hid_read_timeout(hid_device *handle, unsigned char *out, size_t capacity, int timeout)
{
	unsigned char frame[MLINK_MAX_FRAME];
	size_t count;
	if (handle != &device || capacity != 65 || timeout < 0 || !descriptors)
		forbidden("fake_read_framing");
	reads++;
	if (!strcmp(scenario, "signal-term") && !signal_sent) {
		signal_sent = 1; event("READY");
		if (raise(SIGTERM)) forbidden("self_signal");
		event(nut_guarded_dump_signal_requested() ? "NUT_SIGNAL_FLAG=1" : "NUT_SIGNAL_FLAG=0");
		return 0;
	}
	if (!report_queued) {
		const struct timespec pause = {0, 10000000L};
		nanosleep(&pause, NULL); return 0;
	}
	if (!protocol_initialized) forbidden("read_before_init");
	count = fixture_microlink_frame(frame_kind, next_writes > 0, frame, sizeof(frame));
	if (!count || count > 63) forbidden("fixture_frame");
	memset(out, 0, 64); out[0] = 7;
	memcpy(out + 1, frame, count);
	report_queued = 0;
	count_event("INPUT_FRAME", reads);
	return 64;
}
void hid_close(hid_device *handle)
{
	if (handle != &device) forbidden("fake_close");
	count_event("HID_CLOSE", ++closes);
}
int fixture_native_clock_gettime(clockid_t id, struct timespec *now)
{
	if (id != CLOCK_MONOTONIC || !now) return -1;
	now->tv_sec = (time_t)(native_ms / 1000);
	now->tv_nsec = (long)(native_ms % 1000) * 1000000L;
	return 0;
}

static int private_directory(const char *path, char *canonical, size_t capacity)
{
	struct stat st;
	char resolved[PATH_MAX];
	if (!path || lstat(path, &st) || !S_ISDIR(st.st_mode) || st.st_uid != getuid()
	 || (st.st_mode & 0777) != 0700 || !realpath(path, resolved)
	 || strcmp(path, resolved) || strlen(resolved) >= capacity) return 0;
	memcpy(canonical, resolved, strlen(resolved) + 1); return 1;
}
static void final_observer(void)
{
	char line[256];
	if (snprintf(line, sizeof(line),
		"FINAL init=%u open=%u layout=%u read=%u write=%u close=%u exit=%u update=%u dump=%u cleanup=%u dataok=%u flag=%d",
		inits, opens, descriptors, reads, writes, closes, exits, updates, dumps,
		cleanups, dataok, nut_guarded_dump_signal_requested()) >= (int)sizeof(line)) _Exit(126);
	/* The final observer runs after real NUT atexit cleanup. No driver state
	 * is assigned or metric qualified; the Python runner checks these facts. */
	if (++event_count > 512 || fprintf(events, "%s\n", line) < 0 || fflush(events)) _Exit(126);
}
int main(int argc, char **argv)
{
	char conf[PATH_MAX], expected_conf[PATH_MAX], marker[PATH_MAX];
	const char *state = getenv("NUT_STATEPATH"), *config = getenv("NUT_CONFPATH");
	int fd;
	char *driver_argv[] = {
		"full-nut-hidapi-fake", "-s", "fixture", "-d", "1",
		"-x", "hidapi_shared", "-x", "guarded_monitor", "-x", "port=auto",
		"-x", "hid_fallback=no", "-x", "guard_probe_attempts=1",
		"-x", "guard_vid=1234", "-x", "guard_pid=5678", "-x", "guard_deadline=20", NULL
	};
	if (argc != 2) return 2;
	scenario = argv[1];
	if (strcmp(scenario, "metrics-dump") && strcmp(scenario, "metadata-only")
	 && strcmp(scenario, "bad-checksum") && strcmp(scenario, "signal-term")
	 && strcmp(scenario, "invalid-hid-descriptor") && strcmp(scenario, "expiry-after-init")) return 2;
	if (!private_directory(state, state_directory, sizeof(state_directory))
	 || !private_directory(config, conf, sizeof(conf)) || strlen(state_directory) < 6
	 || strcmp(state_directory + strlen(state_directory) - 6, "/state")) return 2;
	if (snprintf(expected_conf, sizeof(expected_conf), "%.*s/conf", (int)(strlen(state_directory) - 6), state_directory) >= (int)sizeof(expected_conf)
	 || strcmp(expected_conf, conf) || !getenv("NUT_DEBUG_SYSLOG")
	 || strcmp(getenv("NUT_DEBUG_SYSLOG"), "stderr")) return 2;
	if (snprintf(marker, sizeof(marker), "%s/full-fake.events", state_directory) >= (int)sizeof(marker)) return 2;
	fd = open(marker, O_CREAT | O_EXCL | O_WRONLY | O_NOFOLLOW, 0600);
	if (fd < 0) return 2;
	events = fdopen(fd, "w");
	if (!events) { close(fd); return 2; }
	if (setenv("NUT_QUIET_INIT_UPSNOTIFY", "1", 1) || atexit(final_observer)) return 2;
	if (!strcmp(scenario, "metadata-only")) frame_kind = FIXTURE_PAGE0_ONLY;
	if (!strcmp(scenario, "bad-checksum")) frame_kind = FIXTURE_BAD_CHECKSUM;
	memset(&info, 0, sizeof(info));
	info.path = "synthetic-full-nut"; info.vendor_id = 0x1234; info.product_id = 0x5678;
	info.bus_type = HID_API_BUS_USB; info.interface_number = 0;
	event("WRAPPER_VALIDATED");
	return nut_real_main((int)(sizeof(driver_argv) / sizeof(driver_argv[0]) - 1), driver_argv);
}
