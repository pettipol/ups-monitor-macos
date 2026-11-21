/* SPDX-License-Identifier: GPL-2.0-or-later
 * Whole operational driver fake host. Derived page fixtures from the admitted
 * replay_continuous_pacing.c (2c5ca61e5f675e4e13bd1f1eb3f775d3a1c725efc3f6721bf6cd40374a769653).
 * Never compile/link the actual native host or any HIDAPI implementation.
 * This TU must NOT receive the driver-only fwrite/fflush aliases. */
#if !defined(MLINK_HIDAPI_NATIVE_CANDIDATE) || !defined(MLINK_HIDAPI_OPERATIONAL_V2) \
	|| !defined(MLINK_HIDAPI_CONTINUOUS_REPLAY) \
	|| !defined(MLINK_OPERATIONAL_REPLAY_HOOKS) || !MLINK_OPERATIONAL_REPLAY_HOOKS
#error "This host is only for the production-interface operational fake replay"
#endif
#if defined(MLINK_HIDAPI_SHARED_TEST) || defined(fwrite) || defined(fflush)
#error "Test binding and driver-only I/O aliases are forbidden in the host TU"
#endif
#include "apcmicrolink-hidapi-native.h"
#include "apcmicrolink-hidapi-session.h"
#include "replay_operational_hooks.h"
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <time.h>
#include <errno.h>
#include <inttypes.h>
#include <limits.h>

#define OUTPUT_LIMIT UINT64_C(1048576)
#define COUNTER_LIMIT UINT64_C(10000000)
#define VIRTUAL_LIMIT INT64_C(900000)

typedef enum {
	SC_HEALTHY, SC_HIGH_ANCHOR, SC_STALE, SC_PARTIAL, SC_STOP_PRE_OPEN,
	SC_STOP_LAYOUT, SC_STOP_READ, SC_READ_TRANSPORT_ERROR, SC_STOP_WRITE, SC_STOP_CLEANUP,
	SC_CLEANUP_SHORT, SC_CLEANUP_LATE, SC_CLOCK_REGRESSION,
	SC_FLUSH_STARTUP_14000, SC_FLUSH_STARTUP_10000, SC_FLUSH_STARTUP_10001,
	SC_PRE_OUTPUT_STALE, SC_FLUSH_ACTIVE_STALE,
	SC_PRE_OPEN_DISPOSE_FAIL, SC_PRE_OPEN_POSTCLOCK_INVALID,
	SC_STOP_BEFORE_WAIT, SC_STOP_BEFORE_PUBLISHED, SC_ERROR_BEFORE_STOP,
	SC_COUNT
} scenario_t;
static const char *const scenario_names[SC_COUNT]={
	"healthy-700s", "high-absolute-anchor", "stale-only", "partial-only", "stop-pre-open",
	"stop-layout", "stop-read", "read-transport-error", "stop-write", "stop-cleanup",
	"cleanup-short", "cleanup-late", "clock-regression",
	"flush-startup-14000", "flush-startup-10000", "flush-startup-10001",
	"pre-output-stale", "flush-active-stale",
	"pre-open-dispose-fail", "pre-open-postclock-invalid",
	"stop-before-wait", "stop-before-published", "error-before-stop"
};
typedef struct replay_host {
	scenario_t scenario;
	int configured, stream_entered, stop_latched, report_pending, live_handle;
	int transport_error_latched;
	int summary_emitted, prepared_hook_used, regression_sent, active_page2_seen;
	int sample_pending_flush, overflow, invalid_write, disposed;
	int (*owner_stop)(void *);
	void *owner_stop_user;
	int64_t now_ms, anchor_ms, last_clock_ms, last_next_ms;
	uint64_t create_calls, init_calls, select_calls, open_calls, layout_calls;
	uint64_t close_calls, dispose_calls, read_calls, clock_calls, wait_calls;
	uint64_t handshake_stop, cleanup_stop, init_writes, next_writes, other_writes;
	uint64_t ordinary_after_cleaning, cleanup_restop, stop_requests;
	uint64_t read_error_injections, ordinary_after_transport_error;
	uint64_t sample_writes, sample_flushes, end_writes, output_bytes, regression_calls;
	uint64_t finish_clock_calls, pre_open_hooks, stream_hooks, prepared_hooks;
	uint64_t before_wait_hooks, before_published_hooks;
	uint64_t next_before_wait, next_before_published;
	uint64_t max_next_gap_ms;
	unsigned char report[64];
} replay_host_t;
static replay_host_t host;
static void report_summary(void);

static void fail_closed(void)
{
	fputs("OPERATIONAL_REPLAY_ERROR closed_contract\n",stderr);
	_Exit(124);
}
static void increment(uint64_t *counter)
{
	if (*counter>=COUNTER_LIMIT) fail_closed();
	(*counter)++;
}
static void configure(void)
{
	const char *value;
	if (host.configured) return;
	host.configured=1;
	value=getenv("MLINK_OPERATIONAL_REPLAY_SCENARIO");
	if (value==NULL) fail_closed();
	for (size_t i=0;i<SC_COUNT;i++) {
		if (strcmp(value,scenario_names[i])==0) {
			host.scenario=(scenario_t)i;
			if (host.scenario==SC_HIGH_ANCHOR)
				host.anchor_ms=INT64_C(4294967296)+12345;
			host.now_ms=host.anchor_ms;
			return;
		}
	}
	fail_closed();
}
static int64_t elapsed(void) { return host.now_ms-host.anchor_ms; }
static void request_stop(void)
{
	if (host.stop_latched) return;
	host.stop_latched=1;
	increment(&host.stop_requests);
	/* Existing NUT handler in this same fake process; never signal another. */
	if (raise(SIGTERM)!=0) fail_closed();
}
static void advance(int64_t amount)
{
	if (amount<0 || host.now_ms>INT64_MAX-amount) fail_closed();
	host.now_ms+=amount;
	if (elapsed()>VIRTUAL_LIMIT) fail_closed();
	if ((host.scenario==SC_HEALTHY || host.scenario==SC_HIGH_ANCHOR)
	 && elapsed()>=700500) request_stop();
	else if ((host.scenario==SC_STOP_CLEANUP || host.scenario==SC_CLEANUP_SHORT
	 || host.scenario==SC_CLEANUP_LATE) && elapsed()>=10000) request_stop();
}
static void advance_to(int64_t target)
{
	if (target<elapsed()) fail_closed();
	advance(target-elapsed());
}
static mlink_health_snapshot_t health(void)
{ return mlink_shared_operational_snapshot(); }

/* Same admitted fake wall/monotonic interposition used by the pacing replay. */
time_t time(time_t *output)
{
	time_t result;
	configure();
	result=(time_t)1700000000+(time_t)(host.now_ms/1000);
	if (output!=NULL) *output=result;
	return result;
}
int clock_gettime(clockid_t clock_id, struct timespec *output)
{
	int64_t ms;
	configure(); ms=host.now_ms;
	if (clock_id==CLOCK_REALTIME) ms+=INT64_C(1700000000000);
	else if (clock_id!=CLOCK_MONOTONIC) { errno=EINVAL; return -1; }
	output->tv_sec=(time_t)(ms/1000);
	output->tv_nsec=(long)((ms%1000)*1000000);
	return 0;
}

static void queue_page(unsigned char id, const unsigned char data[48])
{
	unsigned char frame[51]={0};
	unsigned int c0=0,c1=0;
	frame[0]=id; memcpy(frame+1,data,48);
	for (size_t i=0;i<49;i++) { c0=(c0+frame[i])%255U; c1=(c1+c0)%255U; }
	frame[49]=(unsigned char)(255U-((c0+c1)%255U));
	frame[50]=(unsigned char)(255U-((c0+frame[49])%255U));
	memset(host.report,0,sizeof(host.report)); host.report[0]=1;
	memcpy(host.report+1,frame,sizeof(frame)); host.report_pending=1;
}
static void queue_protocol_page(void)
{
	unsigned char data[48]={0};
	static const unsigned char definition[]={
		0xF8U,2U,0xFEU,4U,0x0AU,0xFEU,5U,
		0x20U,0x9FU,0x21U,0x22U,0xFFU,0xFEU,6U,
		0x25U,0x27U,0xFFU,0xFEU,7U,0x25U,0x26U,0x27U,
		0x28U,0x2AU,0x2BU,0x49U,0xFFU,0xFFU,0xFFU,0xFFU
	};
	data[0]=1; data[1]=48; data[2]=3;
	data[4]=1; data[5]=1; data[6]=0x08;
	data[8]=1; data[10]=1; data[11]=0;
	memcpy(data+12,definition,sizeof(definition)); queue_page(0,data);
}
static void queue_measurement_page(void)
{
	unsigned char data[48]={0};
	static const unsigned char values[]={
		0x00U,0x02U,0x64U,0x00U,0x0EU,0x10U,0x01U,0x80U,
		0x0CU,0x80U,0x1EU,0x00U,0x1EU,0x00U,0x1EU,0x00U,
		0x00U,0xA0U,0x1EU,0x00U,0x12U,0xCCU,0x03U,0x84U,
		0x04U,0xB0U,0x16U,0x39U
	};
	memcpy(data,values,sizeof(values)); queue_page(1,data);
}
static void queue_unrelated_page(void)
{ unsigned char data[48]; memset(data,0x5a,sizeof(data)); queue_page(2,data); }

static int fake_ok(void *user) { (void)user; return 0; }
static int fake_init(void *user)
{ (void)user; increment(&host.init_calls); return 0; }
static int fake_select(void *user, unsigned int *count)
{ (void)user; increment(&host.select_calls); *count=1; return 0; }
static int fake_open(void *user)
{
	(void)user; increment(&host.open_calls);
	if (host.open_calls!=1 || host.live_handle) fail_closed();
	host.live_handle=1; return 0;
}
static int fake_layout(void *user, mlink_shared_layout_t *out)
{
	(void)user; increment(&host.layout_calls);
	*out=(mlink_shared_layout_t){1,1,2,MLINK_SHARED_INPUT,MLINK_SHARED_OUTPUT,64,64};
	if (host.scenario==SC_STOP_LAYOUT) request_stop();
	return 0;
}
static ssize_t fake_read(void *user, unsigned char *out, size_t capacity,
	unsigned int timeout_ms)
{
	(void)user; increment(&host.read_calls);
	if (health().phase>=MLINK_HEALTH_CLEANING) increment(&host.ordinary_after_cleaning);
	if (host.transport_error_latched) {
		increment(&host.ordinary_after_transport_error);
		return -1;
	}
	if ((host.scenario==SC_READ_TRANSPORT_ERROR || host.scenario==SC_ERROR_BEFORE_STOP)
	 && host.stream_entered
	 && health().publications>=1) {
		host.transport_error_latched=1;
		increment(&host.read_error_injections);
		return -1;
	}
	if (!host.report_pending) { advance((int64_t)timeout_ms); return 0; }
	if (capacity<sizeof(host.report)) return -1;
	if (host.stream_entered) {
		if (host.scenario==SC_FLUSH_ACTIVE_STALE && health().publications==1) {
			/* First post-publication page 1 is truly received at 5,000 ms.
			 * The following unrelated page moves time to 9,000 ms. */
			if (host.report[1]==2 && !host.active_page2_seen) {
				host.active_page2_seen=1; advance_to(9000);
			}
		} else advance(200);
		if (host.scenario==SC_STOP_READ && health().publications>=1) request_stop();
	}
	memcpy(out,host.report,sizeof(host.report)); host.report_pending=0;
	return (ssize_t)sizeof(host.report);
}
static ssize_t fake_write(void *user, const unsigned char *out, size_t length)
{
	mlink_health_snapshot_t snap=health();
	unsigned char command;
	(void)user;
	if (length!=64 || out[0]!=2 || !host.live_handle) { host.invalid_write=1; return -1; }
	for (size_t i=2;i<length;i++) if (out[i]!=0) host.invalid_write=1;
	command=out[1];
	if (host.transport_error_latched && command!=0xF7)
		increment(&host.ordinary_after_transport_error);
	if (snap.phase>=MLINK_HEALTH_CLEANING && command!=0xF7)
		increment(&host.ordinary_after_cleaning);
	if (command==0xF7) {
		if (snap.phase==MLINK_HEALTH_CLEANING) {
			increment(&host.cleanup_stop);
			if (host.cleanup_stop>1) fail_closed();
			if (host.scenario==SC_STOP_CLEANUP) {
				increment(&host.cleanup_restop);
				mlink_shared_operational_stop();
				if (raise(SIGTERM)!=0) fail_closed();
			}
			if (host.scenario==SC_ERROR_BEFORE_STOP) request_stop();
			if (host.scenario==SC_CLEANUP_SHORT) return 63;
			if (host.scenario==SC_CLEANUP_LATE) advance(2000);
		} else increment(&host.handshake_stop);
	} else if (command==0xFD) {
		increment(&host.init_writes);
		if (host.init_writes>1) fail_closed();
		queue_protocol_page();
	} else if (command==0xFE) {
		if (host.next_writes!=0) {
			uint64_t gap=(uint64_t)(host.now_ms-host.last_next_ms);
			if (gap>host.max_next_gap_ms) host.max_next_gap_ms=gap;
		}
		host.last_next_ms=host.now_ms; increment(&host.next_writes);
		if (host.stream_entered && host.scenario==SC_STOP_WRITE && snap.publications>=1)
			request_stop();
		if (host.stream_entered && (host.scenario==SC_STALE || host.scenario==SC_PRE_OUTPUT_STALE
		 || (host.scenario==SC_FLUSH_ACTIVE_STALE && snap.publications==1 && host.active_page2_seen)))
			queue_unrelated_page();
		else if (host.next_writes%2U==1U) queue_measurement_page();
		else queue_unrelated_page();
		if (host.stream_entered && host.scenario==SC_PARTIAL) {
			/* Same admitted page prefix, incomplete protocol body/checksum. */
			memset(host.report+13,0,sizeof(host.report)-13);
		}
	} else { increment(&host.other_writes); host.invalid_write=1; return -1; }
	return host.invalid_write ? -1 : (ssize_t)length;
}
static int fake_close(void *user)
{
	(void)user; increment(&host.close_calls);
	if (!host.live_handle || host.close_calls>1) fail_closed();
	host.live_handle=0; return 0;
}
static int fake_stopped(void *user)
{
	(void)user;
	return host.stop_latched || (host.owner_stop!=NULL && host.owner_stop(host.owner_stop_user));
}
static int fake_clock(void *user, int64_t *now)
{
	(void)user; increment(&host.clock_calls);
	if (host.scenario==SC_CLOCK_REGRESSION && elapsed()>=1000 && !host.regression_sent) {
		host.regression_sent=1; increment(&host.regression_calls);
		*now=host.last_clock_ms-1; return 0;
	}
	*now=host.now_ms; host.last_clock_ms=*now; return 0;
}
static const mlink_shared_host_ops_t ops={fake_init,fake_ok,fake_select,fake_open,
	fake_layout,fake_read,fake_write,fake_close,fake_stopped,fake_clock,NULL};

int mlink_hidapi_native_create(const mlink_hidapi_native_config_t *config,
	mlink_hidapi_native_binding_t *binding)
{
	configure(); increment(&host.create_calls);
	if (host.create_calls!=1 || config==NULL || binding==NULL || binding->ops!=NULL)
		return -1;
	host.owner_stop=config->stop_requested; host.owner_stop_user=config->stop_user;
	binding->ops=&ops; binding->user=&host; return 0;
}
int mlink_hidapi_native_dispose(mlink_hidapi_native_binding_t *binding)
{
	increment(&host.dispose_calls);
	if (binding==NULL || binding->ops!=&ops || binding->user!=&host
	 || host.live_handle || host.dispose_calls!=1) return -1;
	if (host.scenario==SC_PRE_OPEN_DISPOSE_FAIL) return -1;
	host.disposed=1; memset(binding,0,sizeof(*binding)); return 0;
}
int mlink_hidapi_native_post_finish_clock_ms(int64_t *now)
{
	increment(&host.finish_clock_calls);
	if (now==NULL || host.scenario==SC_PRE_OPEN_POSTCLOCK_INVALID) return -1;
	*now=host.now_ms; return 0;
}
int mlink_continuous_replay_wait(unsigned int wait_ms)
{
	if (wait_ms>100) return 0;
	increment(&host.wait_calls); advance((int64_t)wait_ms); return 1;
}

size_t mlink_operational_replay_fwrite(const void *ptr, size_t size,
	size_t count, FILE *stream)
{
	char prefix[129];
	size_t bytes, copied, result;
	int sample, end;
	if (stream!=stdout) return fwrite(ptr,size,count,stream);
	if (ptr==NULL || size!=1 || count>8192 || count>OUTPUT_LIMIT-host.output_bytes) {
		host.overflow=1; return 0;
	}
	bytes=count; copied=bytes<sizeof(prefix)-1 ? bytes : sizeof(prefix)-1;
	memcpy(prefix,ptr,copied); prefix[copied]='\0';
	sample=strstr(prefix,"\"type\":\"sample\"")!=NULL;
	end=strstr(prefix,"\"type\":\"end\"")!=NULL;
	if (sample==end) fail_closed();
	result=fwrite(ptr,size,count,stream);
	host.output_bytes+=(uint64_t)result;
	host.sample_pending_flush=sample && result==count;
	if (result==count) {
		if (sample) increment(&host.sample_writes);
		else increment(&host.end_writes);
	}
	return result;
}
int mlink_operational_replay_fflush(FILE *stream)
{
	int rc=fflush(stream);
	if (stream==stdout && host.sample_pending_flush && rc==0) {
		host.sample_pending_flush=0; increment(&host.sample_flushes);
		if (host.sample_flushes==1) {
			if (host.scenario==SC_FLUSH_STARTUP_14000) advance_to(14000);
			else if (host.scenario==SC_FLUSH_STARTUP_10000) advance_to(10000);
			else if (host.scenario==SC_FLUSH_STARTUP_10001) advance_to(10001);
			else if (host.scenario==SC_FLUSH_ACTIVE_STALE) advance_to(5000);
		} else if (host.sample_flushes==2 && host.scenario==SC_FLUSH_ACTIVE_STALE)
			advance_to(16000);
	}
	return rc;
}

static void report_summary(void)
{
	mlink_health_snapshot_t snap=health();
	if (host.summary_emitted) return;
	host.summary_emitted=1;
	fprintf(stderr,"OPERATIONAL_REPLAY_SUMMARY {\"schema\":1,\"scenario\":\"%s\","
		"\"anchor_ms\":%" PRId64 ",\"elapsed_ms\":%" PRId64 ","
		"\"create\":%" PRIu64 ",\"init\":%" PRIu64 ",\"select\":%" PRIu64 ","
		"\"open\":%" PRIu64 ",\"layout\":%" PRIu64 ",\"close\":%" PRIu64 ","
		"\"dispose\":%" PRIu64 ",\"disposed\":%d,\"read\":%" PRIu64 ","
		"\"wait\":%" PRIu64 ",\"clock\":%" PRIu64 ",\"finish_clock\":%" PRIu64 ","
		"\"handshake_stop\":%" PRIu64 ",\"cleanup_stop\":%" PRIu64 ","
		"\"init_byte\":%" PRIu64 ",\"next\":%" PRIu64 ",\"other_write\":%" PRIu64 ","
		"\"ordinary_after_cleaning\":%" PRIu64 ",\"cleanup_restop\":%" PRIu64 ","
		"\"stop_requests\":%" PRIu64 ",\"sample_writes\":%" PRIu64 ","
		"\"sample_flushes\":%" PRIu64 ",\"end_writes\":%" PRIu64 ","
		"\"stdout_bytes\":%" PRIu64 ",\"regressions\":%" PRIu64 ","
		"\"max_next_gap_ms\":%" PRIu64 ",\"publications\":%" PRIu64 ",",
		scenario_names[host.scenario],host.anchor_ms,elapsed(),host.create_calls,
		host.init_calls,host.select_calls,host.open_calls,host.layout_calls,
		host.close_calls,host.dispose_calls,host.disposed,host.read_calls,
		host.wait_calls,host.clock_calls,host.finish_clock_calls,host.handshake_stop,
		host.cleanup_stop,host.init_writes,host.next_writes,host.other_writes,
		host.ordinary_after_cleaning,host.cleanup_restop,host.stop_requests,
		host.sample_writes,host.sample_flushes,host.end_writes,host.output_bytes,
		host.regression_calls,host.max_next_gap_ms,snap.publications);
	if (host.scenario==SC_STOP_BEFORE_WAIT || host.scenario==SC_STOP_BEFORE_PUBLISHED)
		fprintf(stderr,"\"before_wait_hooks\":%" PRIu64 ",\"before_published_hooks\":%" PRIu64 ","
			"\"next_before_wait\":%" PRIu64 ",\"next_before_published\":%" PRIu64 ",",
			host.before_wait_hooks,host.before_published_hooks,
			host.next_before_wait,host.next_before_published);
	fprintf(stderr,"\"minimum_observed_ms\":null,\"minimum_observed_measured\":false,"
		"\"phase\":%d,\"reason\":%d,\"cleanup_failed\":%d,"
		"\"overflow\":%d,\"invalid_write\":%d",
		(int)snap.phase,(int)snap.reason,snap.cleanup_failed,host.overflow,host.invalid_write);
	if (host.scenario==SC_READ_TRANSPORT_ERROR || host.scenario==SC_ERROR_BEFORE_STOP)
		fprintf(stderr,",\"read_error_injections\":%" PRIu64
			",\"ordinary_after_transport_error\":%" PRIu64,
			host.read_error_injections,host.ordinary_after_transport_error);
	fputs("}\n",stderr);
}
void mlink_operational_replay_checkpoint(unsigned int point)
{
	configure();
	if (point==MLINK_REPLAY_PRE_OPEN) {
		increment(&host.pre_open_hooks);
		if (host.pre_open_hooks!=1) fail_closed();
		if (host.scenario==SC_STOP_PRE_OPEN || host.scenario==SC_PRE_OPEN_DISPOSE_FAIL
		 || host.scenario==SC_PRE_OPEN_POSTCLOCK_INVALID) request_stop();
	} else if (point==MLINK_REPLAY_STREAM_ENTER) {
		increment(&host.stream_hooks); host.stream_entered=1;
		if (host.stream_hooks!=1) fail_closed();
		if (host.scenario==SC_FLUSH_STARTUP_14000 || host.scenario==SC_FLUSH_STARTUP_10000
		 || host.scenario==SC_FLUSH_STARTUP_10001 || host.scenario==SC_PRE_OUTPUT_STALE)
			advance_to(9000);
	} else if (point==MLINK_REPLAY_PRE_OUTPUT) {
		increment(&host.prepared_hooks);
		if (host.scenario==SC_PRE_OUTPUT_STALE && !host.prepared_hook_used) {
			host.prepared_hook_used=1; advance_to(10001);
		}
		/* Stop a boundary-success case only after its publication was truly
		 * committed, as observed on a later turn through the shared snapshot. */
		if (host.scenario==SC_FLUSH_STARTUP_10000 && health().publications>=1)
			request_stop();
	} else if (point==MLINK_REPLAY_BEFORE_WAIT) {
		increment(&host.before_wait_hooks);
		host.next_before_wait=host.next_writes;
		if (host.scenario==SC_STOP_BEFORE_WAIT) {
			if (host.before_wait_hooks>1) fail_closed();
			request_stop();
		}
	} else if (point==MLINK_REPLAY_BEFORE_PUBLISHED) {
		increment(&host.before_published_hooks);
		host.next_before_published=host.next_writes;
		if (host.scenario==SC_STOP_BEFORE_PUBLISHED) {
			if (host.before_published_hooks>1) fail_closed();
			request_stop();
		}
	} else if (point==MLINK_REPLAY_FINISHED) report_summary();
	else fail_closed();
}

/* Register before true NUT main so CLI rejection also leaves a zero-I/O
 * observation. LIFO ordering makes this run after the driver's cleanup.
 * FINISHED may emit earlier after End; the final callback is idempotent. */
__attribute__((constructor)) static void replay_before_main(void)
{
	configure();
	if (atexit(report_summary)!=0) fail_closed();
}
