/* SPDX-License-Identifier: GPL-2.0-or-later
 * Reuse the synthetic transport host; run unchanged v1 tests separately
 * because their final close-failure case intentionally retains ownership.
 * No native binding, HID library, threads, device or subprocesses. */
#if !defined(MLINK_HIDAPI_SHARED_TEST) || !defined(MLINK_HIDAPI_OPERATIONAL_V2)
#error "This test requires the fake-only operational v2 build"
#endif
#ifdef MLINK_HIDAPI_NATIVE_CANDIDATE
#error "Native host is forbidden in this test"
#endif
#include "apcmicrolink-hidapi-session.h"
#define main unchanged_v1_main
#include "test_hidapi_shared_transport.c"
#undef main

static int stop_write, stop_close, late_close, late_write, late_open, late_read;
static int64_t scripted_clock_values[8];
static size_t scripted_clock_count, scripted_clock_position;

static void set_clock_script(const int64_t *values, size_t count)
{
	scripted_clock_count=count;
	scripted_clock_position=0;
	for (size_t i=0;i<count;i++) scripted_clock_values[i]=values[i];
}

static int v2_clock(void *p, int64_t *now)
{
	if (scripted_clock_position<scripted_clock_count) {
		*now=scripted_clock_values[scripted_clock_position++];
		return 0;
	}
	return f_clock(p,now);
}

static int v2_open(void *p)
{
	fake_host_t *f=p;
	int rc=f_open(p);
	if (late_open) f->now += 40000;
	return rc;
}
static ssize_t v2_write(void *p, const unsigned char *src, size_t len)
{
	fake_host_t *f=p;
	ssize_t rc=f_write(p,src,len);
	if (stop_write) f->stop=1;
	if (late_write) f->now += 20000;
	return rc;
}
static ssize_t v2_read(void *p, unsigned char *dst, size_t cap, unsigned int timeout_ms)
{
	fake_host_t *f=p;
	ssize_t rc=f_read(p,dst,cap,timeout_ms);
	if (late_read) f->now += 20000;
	return rc;
}
static int v2_close(void *p)
{
	fake_host_t *f=p;
	int rc=f_close(p);
	if (stop_close) mlink_shared_operational_stop();
	if (late_close) f->now += 2000;
	return rc;
}
static const mlink_shared_host_ops_t health_ops={f_init,f_exclusive,f_select,
	v2_open,f_layout,v2_read,v2_write,v2_close,f_stop,v2_clock,f_admission_diagnostic};

static int begin_health(fake_host_t *f)
{
	init_fake(f);
	stop_write=stop_close=late_close=late_write=late_open=late_read=0;
	set_clock_script(NULL,0);
	return mlink_shared_test_bind(&health_ops,f) && mlink_shared_operational_begin();
}
static int ready_health(fake_host_t *f)
{
	return begin_health(f) && microlink_usb_open();
}
static int finish_health(fake_host_t *f)
{
	int writes=f->write_calls, reads=f->read_calls;
	unsigned char b=1;
	mlink_shared_operational_stop();
	CHECK(!microlink_usb_send_bytes(&b,1));
	CHECK(microlink_usb_get_char(&b,100000)<0);
	microlink_usb_flush_io();
	CHECK(f->write_calls==writes && f->read_calls==reads);
	CHECK(microlink_usb_cleanup_stop());
	CHECK(f->writes_len==64 && f->writes[0]==8 && f->writes[1]==0xF7);
	for (size_t i=2;i<64;i++) CHECK(f->writes[i]==0);
	CHECK(!microlink_usb_cleanup_stop());
	CHECK(f->write_calls==writes+1);
	microlink_usb_close(); microlink_usb_close();
	CHECK(f->close_calls==1);
	CHECK(mlink_shared_operational_cleanup_complete());
	CHECK(!microlink_usb_cleanup_stop());
	CHECK(!mlink_shared_operational_published(1));
	CHECK(!microlink_usb_open());
	CHECK(!mlink_shared_operational_begin());
	CHECK(mlink_shared_operational_snapshot().phase==MLINK_HEALTH_FINISHED);
	return 0;
}
static int test_healthy_long_session(void)
{
	static fake_host_t f; uint64_t elapsed=999;
	CHECK(ready_health(&f));
	CHECK(!microlink_usb_guard_set_acquisition_seconds(120));
	CHECK(!microlink_usb_cleanup_stop());
	for (int64_t tick=0;tick<=300000;tick+=5000) {
		f.now=tick;
		CHECK(mlink_shared_operational_published((uint64_t)tick));
		CHECK(mlink_shared_operational_elapsed(&elapsed) && elapsed==(uint64_t)tick);
		CHECK(!microlink_usb_guard_expired());
	}
	CHECK(mlink_shared_operational_snapshot().publications==61);
	CHECK(strcmp(f.order,"INSOR")==0);
	CHECK(finish_health(&f)==0);
	init_fake(&f); f.now=5000;
	CHECK(mlink_shared_test_bind(&health_ops,&f));
	CHECK(mlink_shared_operational_begin() && microlink_usb_open());
	f.now=6000; CHECK(mlink_shared_operational_published(1000));
	f.now=7000; CHECK(mlink_shared_operational_published(2000));
	CHECK(mlink_shared_operational_elapsed(&elapsed) && elapsed==2000);
	CHECK(finish_health(&f)==0);
	return 0;
}
static int test_raw_traffic_cannot_renew(void)
{
	static fake_host_t f; unsigned char b=1;
	CHECK(ready_health(&f));
	CHECK(mlink_shared_operational_published(0));
	f.now=14999;
	CHECK(microlink_usb_send_bytes(&b,1));
	queue_report(&f,7,64,0x11);
	CHECK(microlink_usb_get_char(&b,1000000)==1);
	CHECK(f.last_read_timeout==1);
	f.now=15000;
	CHECK(microlink_usb_get_char(&b,0)<0);
	CHECK(mlink_shared_operational_snapshot().reason==MLINK_HEALTH_PROGRESS_DEADLINE);
	CHECK(!mlink_shared_operational_published(15000));
	CHECK(finish_health(&f)==0);
	CHECK(ready_health(&f));
	f.now=34999; CHECK(!microlink_usb_guard_expired());
	f.now=35000; CHECK(microlink_usb_guard_expired());
	CHECK(mlink_shared_operational_snapshot().reason==MLINK_HEALTH_STARTUP_DEADLINE);
	CHECK(finish_health(&f)==0);
	return 0;
}
static int test_bad_refresh_and_clock(void)
{
	static fake_host_t f; uint64_t elapsed;
	CHECK(ready_health(&f));
	CHECK(mlink_shared_operational_published(0)); f.now=1000;
	CHECK(!mlink_shared_operational_published(0));
	CHECK(mlink_shared_operational_snapshot().reason==MLINK_HEALTH_REFRESH);
	CHECK(finish_health(&f)==0);
	CHECK(ready_health(&f)); CHECK(!mlink_shared_operational_published(1));
	CHECK(finish_health(&f)==0);
	CHECK(ready_health(&f)); f.now=10;
	CHECK(mlink_shared_operational_elapsed(&elapsed)); f.now=9;
	CHECK(!mlink_shared_operational_elapsed(&elapsed));
	CHECK(mlink_shared_operational_snapshot().reason==MLINK_HEALTH_CLOCK);
	microlink_usb_close(); CHECK(!mlink_shared_operational_cleanup_complete());
	CHECK(ready_health(&f)); f.clock_fail=1;
	CHECK(microlink_usb_guard_expired()); f.clock_fail=0;
	microlink_usb_close(); CHECK(!mlink_shared_operational_cleanup_complete());
	CHECK(begin_health(&f)); /* checked elapsed representation, no long loop */
	f.now=(int64_t)MLINK_OPERATIONAL_MAX_ELAPSED+1;
	CHECK(!mlink_shared_operational_elapsed(&elapsed));
	CHECK(mlink_shared_operational_snapshot().reason==MLINK_HEALTH_OVERFLOW);
	CHECK(mlink_shared_operational_cleanup_complete());
	init_fake(&f); f.now=INT64_MAX-34999;
	CHECK(mlink_shared_test_bind(&health_ops,&f));
	CHECK(!mlink_shared_operational_begin());
	init_fake(&f); f.now=INT64_MAX-35000;
	CHECK(mlink_shared_test_bind(&health_ops,&f));
	CHECK(mlink_shared_operational_begin() && microlink_usb_open());
	f.now=INT64_MAX-10000;
	CHECK(!mlink_shared_operational_published(25000));
	CHECK(mlink_shared_operational_snapshot().reason==MLINK_HEALTH_OVERFLOW);
	CHECK(finish_health(&f)==0);
	init_fake(&f); f.now=INT64_MAX-35000;
	CHECK(mlink_shared_test_bind(&health_ops,&f));
	CHECK(mlink_shared_operational_begin() && microlink_usb_open());
	f.now=INT64_MAX-1000; mlink_shared_operational_stop();
	CHECK(!microlink_usb_cleanup_stop());
	microlink_usb_close(); CHECK(!mlink_shared_operational_cleanup_complete());
	return 0;
}

static int test_sampled_deadline_transitions(void)
{
	static fake_host_t f;
	uint64_t elapsed=1234U;
	int writes, reads;
	const int64_t startup_times[]={34999,35000};
	const int64_t progress_times[]={14999,15000};
	const int64_t get_char_times[]={14998,14999,15000};
	const int64_t remaining_times[]={14996,14997,14998,14998,14999,14999,15000};
	unsigned char byte=0;

	/* elapsed's first clock is before startup deadline, its result clock is at it. */
	CHECK(ready_health(&f));
	writes=f.write_calls; reads=f.read_calls; f.now=35000;
	set_clock_script(startup_times,2);
	CHECK(!mlink_shared_operational_elapsed(&elapsed));
	CHECK(elapsed==1234U);
	CHECK(mlink_shared_operational_snapshot().reason==MLINK_HEALTH_STARTUP_DEADLINE);
	CHECK(mlink_shared_operational_snapshot().phase==MLINK_HEALTH_CLEANING);
	CHECK(f.write_calls==writes && f.read_calls==reads);
	CHECK(finish_health(&f)==0);

	/* The same two-read transition in ACTIVE latches progress expiry, not I/O. */
	CHECK(ready_health(&f));
	CHECK(mlink_shared_operational_published(0));
	writes=f.write_calls; reads=f.read_calls; f.now=15000;
	set_clock_script(progress_times,2);
	CHECK(!mlink_shared_operational_elapsed(&elapsed));
	CHECK(mlink_shared_operational_snapshot().reason==MLINK_HEALTH_PROGRESS_DEADLINE);
	CHECK(mlink_shared_operational_snapshot().publications==1);
	CHECK(f.write_calls==writes && f.read_calls==reads);
	CHECK(finish_health(&f)==0);

	/* get_char's own second clock sample can cross the progress deadline. */
	CHECK(ready_health(&f));
	CHECK(mlink_shared_operational_published(0));
	writes=f.write_calls; reads=f.read_calls; f.now=15000;
	set_clock_script(get_char_times,3);
	CHECK(microlink_usb_get_char(&byte,1000000)<0);
	CHECK(mlink_shared_operational_snapshot().reason==MLINK_HEALTH_PROGRESS_DEADLINE);
	CHECK(f.write_calls==writes && f.read_calls==reads);
	CHECK(finish_health(&f)==0);

	/* remaining_ms checks its own second sample before any read is admitted. */
	CHECK(ready_health(&f));
	CHECK(mlink_shared_operational_published(0));
	writes=f.write_calls; reads=f.read_calls; f.now=15000;
	set_clock_script(remaining_times,7);
	CHECK(microlink_usb_get_char(&byte,1000000)<0);
	CHECK(mlink_shared_operational_snapshot().reason==MLINK_HEALTH_PROGRESS_DEADLINE);
	CHECK(f.write_calls==writes && f.read_calls==reads);
	CHECK(finish_health(&f)==0);
	return 0;
}

static int test_cleanup_deadline_and_boundaries(void)
{
	static fake_host_t f; unsigned char b=1;
	CHECK(ready_health(&f)); mlink_shared_operational_fail();
	CHECK(mlink_shared_operational_snapshot().reason==MLINK_HEALTH_IO);
	CHECK(finish_health(&f)==0);
	CHECK(mlink_shared_operational_snapshot().reason==MLINK_HEALTH_IO);
	CHECK(begin_health(&f)); f.stop=1;
	CHECK(!microlink_usb_open()); CHECK(f.order_len==0);
	CHECK(mlink_shared_operational_cleanup_complete());
	CHECK(begin_health(&f)); f.stop_in_layout=1;
	CHECK(!microlink_usb_open()); CHECK(f.close_calls==1);
	CHECK(mlink_shared_operational_cleanup_complete());
	CHECK(begin_health(&f)); late_open=1;
	CHECK(!microlink_usb_open()); CHECK(f.close_calls==1);
	CHECK(mlink_shared_operational_snapshot().reason==MLINK_HEALTH_STARTUP_DEADLINE);
	CHECK(mlink_shared_operational_cleanup_complete());
	CHECK(ready_health(&f)); f.stop_in_read=1; queue_report(&f,7,64,0x11);
	CHECK(microlink_usb_get_char(&b,1000)<0);
	CHECK(finish_health(&f)==0);
	CHECK(ready_health(&f)); stop_write=1;
	CHECK(!microlink_usb_send_bytes(&b,1)); stop_write=0;
	CHECK(finish_health(&f)==0);
	CHECK(ready_health(&f)); CHECK(mlink_shared_operational_published(0)); late_write=1;
	CHECK(!microlink_usb_send_bytes(&b,1)); late_write=0;
	CHECK(mlink_shared_operational_snapshot().reason==MLINK_HEALTH_PROGRESS_DEADLINE);
	CHECK(finish_health(&f)==0);
	CHECK(ready_health(&f)); CHECK(mlink_shared_operational_published(0)); late_read=1;
	queue_report(&f,7,64,0x11);
	CHECK(microlink_usb_get_char(&b,1000000)<0); late_read=0;
	CHECK(mlink_shared_operational_snapshot().reason==MLINK_HEALTH_PROGRESS_DEADLINE);
	CHECK(finish_health(&f)==0);
	CHECK(ready_health(&f)); f.close_in_read=1; queue_report(&f,7,64,0x11);
	CHECK(microlink_usb_get_char(&b,1000)<0);
	CHECK(f.close_calls==1 && !f.close_early);
	CHECK(mlink_shared_operational_cleanup_complete());
	CHECK(ready_health(&f)); mlink_shared_operational_stop(); f.now=2000;
	CHECK(!microlink_usb_cleanup_stop()); CHECK(f.write_calls==0);
	microlink_usb_close(); CHECK(!mlink_shared_operational_cleanup_complete());
	CHECK(f.close_calls==1 && mlink_shared_operational_snapshot().cleanup_failed);
	CHECK(ready_health(&f)); mlink_shared_operational_stop(); late_write=1;
	CHECK(!microlink_usb_cleanup_stop()); late_write=0;
	CHECK(!microlink_usb_cleanup_stop()); CHECK(f.write_calls==1);
	microlink_usb_close(); CHECK(!mlink_shared_operational_cleanup_complete());
	CHECK(ready_health(&f)); mlink_shared_operational_stop(); late_close=1; stop_close=1;
	microlink_usb_close(); CHECK(f.close_calls==1);
	CHECK(!mlink_shared_operational_cleanup_complete());
	CHECK(ready_health(&f)); mlink_shared_operational_stop(); f.write_result=-1;
	CHECK(!microlink_usb_cleanup_stop());
	CHECK(!microlink_usb_cleanup_stop()); CHECK(f.write_calls==1);
	microlink_usb_close(); CHECK(!mlink_shared_operational_cleanup_complete());
	return 0;
}

int main(void)
{
	int (*tests[])(void)={test_healthy_long_session,test_raw_traffic_cannot_renew,
		test_bad_refresh_and_clock,test_sampled_deadline_transitions,
		test_cleanup_deadline_and_boundaries};
	for (size_t i=0;i<sizeof(tests)/sizeof(tests[0]);i++) {
		if (tests[i]()) return 1;
		mlink_shared_test_unbind();
	}
	puts("PASS fake-only operational health groups=5 healthy_elapsed_ms=300000 opens=1 closes=1");
	return 0;
}
