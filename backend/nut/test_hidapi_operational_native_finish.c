/* SPDX-License-Identifier: GPL-2.0-or-later
 * Native lifecycle seam with local stubs only. Never link native.c/HIDAPI.
 * One closed scenario per process: production preparation is one-shot. */
#if !defined(MLINK_HIDAPI_NATIVE_CANDIDATE) || !defined(MLINK_HIDAPI_OPERATIONAL_V2)
#error "Requires the native lifecycle and operational v2 compile gates"
#endif
#ifdef MLINK_HIDAPI_SHARED_TEST
#error "Test binding is forbidden: this fixture exercises production ownership"
#endif
#include "apcmicrolink-usb.h"
#include "apcmicrolink-hidapi-session.h"
#include "apcmicrolink-hidapi-native.h"
#include <stdio.h>
#include <string.h>

#define CHECK(expr) do { if (!(expr)) { \
	fprintf(stderr,"FAIL native-finish line %d: %s\n",__LINE__,#expr); return 1; \
} } while (0)

typedef enum {
	CASE_CLEAN, CASE_EXPIRED, CASE_POST_INVALID, CASE_POST_REGRESSION,
	CASE_POST_OVERFLOW, CASE_LATE_FINISH, CASE_DISPOSE_FAIL,
	CASE_CLOSE_FAIL, CASE_STOP_FAIL
} scenario_t;

static struct {
	int64_t now;
	scenario_t scenario;
	int created, selected, opened, closed, writes, disposed;
	int live;
	int invalid_write;
} fake;

static int ok(void *user) { (void)user; return 0; }
static int select_one(void *user, unsigned int *count)
{ (void)user; fake.selected++; *count=1; return 0; }
static int open_one(void *user)
{ (void)user; fake.opened++; fake.live=1; return 0; }
static int layout(void *user, mlink_shared_layout_t *out)
{
	(void)user;
	*out=(mlink_shared_layout_t){1,7,8,MLINK_SHARED_INPUT,MLINK_SHARED_OUTPUT,64,64};
	return 0;
}
static ssize_t read_report(void *user, unsigned char *out, size_t size, unsigned int timeout)
{ (void)user; (void)out; (void)size; (void)timeout; return -1; }
static ssize_t write_report(void *user, const unsigned char *out, size_t size)
{
	(void)user; fake.writes++;
	if (!fake.live || size!=64 || out[0]!=8 || out[1]!=0xF7) fake.invalid_write=1;
	for (size_t i=2;i<size;i++) if (out[i]!=0) fake.invalid_write=1;
	return fake.scenario==CASE_STOP_FAIL ? 63 : 64;
}
static int close_one(void *user)
{
	(void)user; fake.closed++;
	if (fake.scenario==CASE_CLOSE_FAIL) return -1;
	fake.live=0; return 0;
}
static int clock_ms(void *user, int64_t *now)
{ (void)user; *now=fake.now; return 0; }
static const mlink_shared_host_ops_t fake_ops={ok,ok,select_one,open_one,layout,
	read_report,write_report,close_one,ok,clock_ms,NULL};

int mlink_hidapi_native_create(const mlink_hidapi_native_config_t *config,
	mlink_hidapi_native_binding_t *binding)
{
	if (config==NULL || binding==NULL || fake.created++) return -1;
	binding->ops=&fake_ops; binding->user=&fake;
	return 0;
}
int mlink_hidapi_native_dispose(mlink_hidapi_native_binding_t *binding)
{
	fake.disposed++;
	if (binding==NULL || fake.live || fake.scenario==CASE_DISPOSE_FAIL) return -1;
	memset(binding,0,sizeof(*binding));
	return 0;
}
int mlink_hidapi_native_post_finish_clock_ms(int64_t *now)
{
	if (fake.scenario==CASE_POST_INVALID) return -1;
	if (fake.scenario==CASE_POST_REGRESSION) *now=fake.now-1;
	else if (fake.scenario==CASE_POST_OVERFLOW)
		*now=1000+(int64_t)MLINK_OPERATIONAL_MAX_ELAPSED+1;
	else if (fake.scenario==CASE_LATE_FINISH) *now=fake.now+2000;
	else *now=fake.now+100;
	return 0;
}

int main(int argc, char **argv)
{
	static const char *const names[]={"clean","expired","post-invalid","post-regression",
		"post-overflow","late-finish","dispose-fail","close-fail","stop-fail"};
	mlink_hidapi_native_config_t config={1,2,ok,NULL};
	mlink_hidapi_session_finish_t finish;
	mlink_health_snapshot_t snapshot;
	uint64_t elapsed=UINT64_MAX;
	unsigned char ordinary=0xFE;
	int found=0, cleanup_ok, elapsed_ok, expected_released, expected_cleanup;
	CHECK(argc==2);
	for (size_t i=0;i<sizeof(names)/sizeof(names[0]);i++) {
		if (strcmp(argv[1],names[i])==0) { fake.scenario=(scenario_t)i; found=1; break; }
	}
	CHECK(found);
	fake.now=1000;
	CHECK(mlink_shared_prepare_native_v2(&config));
	CHECK(microlink_usb_open());
	fake.now=2000;
	CHECK(mlink_shared_operational_published(1000));
	if (fake.scenario==CASE_EXPIRED) {
		fake.now=17000;
		CHECK(microlink_usb_guard_expired());
		CHECK(mlink_shared_operational_snapshot().reason==MLINK_HEALTH_PROGRESS_DEADLINE);
	} else {
		fake.now=3000;
		mlink_shared_operational_stop();
	}
	CHECK(!microlink_usb_send_bytes(&ordinary,1));
	CHECK(microlink_usb_get_char(&ordinary,0)<0);
	CHECK(microlink_usb_cleanup_stop()==(fake.scenario!=CASE_STOP_FAIL));
	CHECK(!microlink_usb_cleanup_stop());
	finish=mlink_shared_finish_native();
	cleanup_ok=mlink_shared_operational_cleanup_complete();
	elapsed_ok=mlink_shared_operational_elapsed(&elapsed);
	snapshot=mlink_shared_operational_snapshot();
	expected_released=fake.scenario!=CASE_DISPOSE_FAIL && fake.scenario!=CASE_CLOSE_FAIL;
	expected_cleanup=fake.scenario==CASE_CLEAN || fake.scenario==CASE_EXPIRED;
	CHECK((finish==MLINK_HIDAPI_SESSION_RELEASED)==expected_released);
	CHECK(cleanup_ok==expected_cleanup);
	if (fake.scenario==CASE_POST_INVALID || fake.scenario==CASE_POST_REGRESSION
	 || fake.scenario==CASE_POST_OVERFLOW) CHECK(!elapsed_ok);
	else {
		CHECK(elapsed_ok);
		if (fake.scenario==CASE_DISPOSE_FAIL || fake.scenario==CASE_CLOSE_FAIL)
			CHECK(elapsed==(uint64_t)(fake.now-1000));
		else if (fake.scenario==CASE_LATE_FINISH) CHECK(elapsed==4000);
		else CHECK(elapsed==(uint64_t)(fake.now+100-1000));
	}
	CHECK(fake.created==1 && fake.selected==1 && fake.opened==1 && fake.closed==1);
	CHECK(fake.writes==1 && !fake.invalid_write);
	CHECK(fake.disposed==(fake.scenario==CASE_CLOSE_FAIL ? 0 : 1));
	CHECK(!mlink_shared_prepare_native_v2(&config));
	CHECK(!mlink_shared_operational_published(9999));
	CHECK(!microlink_usb_open());
	CHECK(!microlink_usb_send_bytes(&ordinary,1));
	CHECK(!microlink_usb_cleanup_stop());
	CHECK((mlink_shared_finish_native()==MLINK_HIDAPI_SESSION_RELEASED)==expected_released);
	CHECK(fake.closed==1 && fake.writes==1);
	CHECK(fake.disposed==(fake.scenario==CASE_CLOSE_FAIL ? 0 : 1));
	if (expected_released) CHECK(snapshot.phase==MLINK_HEALTH_FINISHED);
	else CHECK(snapshot.phase==MLINK_HEALTH_CLEANING);
	if (expected_cleanup) CHECK(!snapshot.cleanup_failed);
	if (fake.scenario==CASE_EXPIRED) CHECK(snapshot.reason==MLINK_HEALTH_PROGRESS_DEADLINE);
	printf("PASS fake-only native finish scenario=%s\n",names[(size_t)fake.scenario]);
	return 0;
}
