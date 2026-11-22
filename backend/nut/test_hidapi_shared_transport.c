#include <apcmicrolink-usb.h>
#include "apcmicrolink-hidapi-shared-host.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* SPDX-License-Identifier: GPL-2.0-or-later */

#ifndef MLINK_HIDAPI_SHARED_TEST
int main(void)
{
	if (microlink_usb_guard_begin(1) != 0 || microlink_usb_open() != 0) return 1;
	puts("PASS production build fails closed without a host binding");
	return 0;
}
#else

#define CHECK(expr) do { if (!(expr)) { \
	fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #expr); return 1; \
} } while (0)

typedef struct fake_host {
	char order[32];
	size_t order_len;
	int init_rc, exclusive_rc, select_rc, open_rc, layout_rc, close_rc;
	int select_count;
	mlink_shared_layout_t layout;
	int stop;
	int clock_fail;
	int64_t now;
	int rollback_clock;
	int diagnostic_calls;
	mlink_admission_diagnostic_t diagnostic;
	int close_calls;
	int close_in_read;
	int close_in_write;
	int close_in_open;
	int in_host_call;
	int close_early;
	int stop_in_read;
	int expire_in_read;
	int stop_in_layout;
	int expire_in_layout;
	int attempt_io_in_layout;
	int io_rejected_in_layout;
	unsigned int last_read_timeout;
	int64_t advance_ms_each_read;
	int write_calls;
	int read_calls;
	int layout_calls;
	ssize_t write_result;
	unsigned char writes[65];
	size_t writes_len;
	struct { unsigned char bytes[65]; ssize_t len; } reads[80];
	size_t read_count, read_pos;
} fake_host_t;

static void mark(fake_host_t *f, char c)
{
	if (f->order_len < sizeof(f->order) - 1) {
		f->order[f->order_len++] = c;
		f->order[f->order_len] = '\0';
	}
}

static int f_init(void *p) { fake_host_t *f=p; mark(f,'I'); return f->init_rc; }
static int f_exclusive(void *p) { fake_host_t *f=p; mark(f,'N'); return f->exclusive_rc; }
static int f_select(void *p, unsigned int *selected_count)
{
	fake_host_t *f=p; mark(f,'S'); *selected_count=(unsigned int)f->select_count; return f->select_rc;
}
static int f_open(void *p)
{
	fake_host_t *f=p; mark(f,'O');
	f->in_host_call=1;
	if (f->close_in_open) microlink_usb_close();
	if (f->close_calls != 0) f->close_early=1;
	f->in_host_call=0;
	return f->open_rc;
}
static int f_layout(void *p, mlink_shared_layout_t *layout)
{
	fake_host_t *f=p;
	unsigned char ch=0, byte=1;
	mark(f,'R'); f->layout_calls++;
	if (f->attempt_io_in_layout) {
		int read_rc=microlink_usb_get_char(&ch,0);
		int write_rc=microlink_usb_send_bytes(&byte,1);
		f->io_rejected_in_layout=(read_rc<0 && write_rc==0);
	}
	if (f->stop_in_layout) f->stop=1;
	if (f->expire_in_layout) f->now=10000;
	*layout=f->layout;
	return f->layout_rc;
}
static ssize_t f_read(void *p, unsigned char *dst, size_t cap, unsigned int timeout_ms)
{
	fake_host_t *f=p;
	f->read_calls++;
	f->last_read_timeout=timeout_ms;
	f->in_host_call=1;
	if (f->close_in_read) microlink_usb_close();
	if (f->close_calls != 0) f->close_early=1;
	if (f->stop_in_read) f->stop=1;
	if (f->expire_in_read) f->now=10000;
	if (f->read_pos >= f->read_count) { f->in_host_call=0; return 0; }
	ssize_t n=f->reads[f->read_pos].len;
	if (n > 0 && (size_t)n <= cap) memcpy(dst,f->reads[f->read_pos].bytes,(size_t)n);
	f->read_pos++;
	f->now+=f->advance_ms_each_read;
	f->in_host_call=0;
	return n;
}
static ssize_t f_write(void *p, const unsigned char *src, size_t len)
{
	fake_host_t *f=p; f->write_calls++;
	f->in_host_call=1;
	if (f->close_in_write) microlink_usb_close();
	f->writes_len=len; memcpy(f->writes,src,len);
	if (f->close_calls != 0) f->close_early=1;
	f->in_host_call=0;
	return f->write_result;
}
static int f_close(void *p)
{
	fake_host_t *f=p; if (f->in_host_call) f->close_early=1;
	f->close_calls++; mark(f,'C'); return f->close_rc;
}
static int f_stop(void *p) { return ((fake_host_t *)p)->stop; }
static int f_clock(void *p, int64_t *now)
{
	fake_host_t *f=p;
	if (f->clock_fail) return -1;
	if (f->rollback_clock) { f->rollback_clock=0; f->now=0; }
	*now=f->now; return 0;
}

static mlink_admission_diagnostic_t f_admission_diagnostic(void *p)
{
	fake_host_t *f=p; f->diagnostic_calls++; return f->diagnostic;
}

static const mlink_shared_host_ops_t ops={f_init,f_exclusive,f_select,f_open,
	f_layout,f_read,f_write,f_close,f_stop,f_clock,f_admission_diagnostic};
static const mlink_shared_host_ops_t legacy_ops={f_init,f_exclusive,f_select,f_open,
	f_layout,f_read,f_write,f_close,f_stop,f_clock,NULL};

static int bind_fake(fake_host_t *f)
{
	mlink_shared_test_unbind();
	return mlink_shared_test_bind(&ops,f);
}

static void init_fake(fake_host_t *f)
{
	mlink_shared_test_unbind();
	memset(f,0,sizeof(*f));
	f->select_count=1;
	f->layout.input_report_id=7;
	f->layout.output_report_id=8;
	f->layout.input_direction=MLINK_SHARED_INPUT;
	f->layout.output_direction=MLINK_SHARED_OUTPUT;
	f->layout.input_report_length=64;
	f->layout.output_report_length=64;
	f->write_result=64;
}

static int ready(fake_host_t *f)
{
	return bind_fake(f) && microlink_usb_guard_begin(10)
		&& microlink_usb_open();
}

static void queue_report(fake_host_t *f, unsigned int id, ssize_t len, unsigned char fill)
{
	size_t i=f->read_count++;
	if (len > 0 && len <= 65) {
		memset(f->reads[i].bytes,fill,(size_t)len);
		f->reads[i].bytes[0]=(unsigned char)id;
	}
	f->reads[i].len=len;
}

static int test_open_order_and_layout(void)
{
	static fake_host_t f; init_fake(&f);
	CHECK(ready(&f)); CHECK(strcmp(f.order,"INSOR")==0);
	CHECK(f.layout_calls==1);
	CHECK(!microlink_usb_open());
	CHECK(bind_fake(&f));
	return 0;
}

static int test_open_rejections(void)
{
	static fake_host_t f; init_fake(&f); f.select_count=0;
	CHECK(bind_fake(&f)); CHECK(microlink_usb_guard_begin(5));
	CHECK(!microlink_usb_open()); CHECK(strcmp(f.order,"INS")==0);
	init_fake(&f); f.select_count=2;
	CHECK(bind_fake(&f)); CHECK(microlink_usb_guard_begin(5));
	CHECK(!microlink_usb_open());
	init_fake(&f); f.layout.input_report_id=0;
	CHECK(bind_fake(&f)); CHECK(microlink_usb_guard_begin(5));
	CHECK(!microlink_usb_open()); CHECK(strcmp(f.order,"INSORC")==0 && f.close_calls==1);
	init_fake(&f); f.layout.input_direction=MLINK_SHARED_OUTPUT;
	CHECK(bind_fake(&f)); CHECK(microlink_usb_guard_begin(5));
	CHECK(!microlink_usb_open()); CHECK(strcmp(f.order,"INSORC")==0 && f.close_calls==1);
	init_fake(&f); f.layout.input_report_length=63;
	CHECK(bind_fake(&f)); CHECK(microlink_usb_guard_begin(5));
	CHECK(!microlink_usb_open()); CHECK(strcmp(f.order,"INSORC")==0 && f.close_calls==1);
	init_fake(&f); f.layout.output_report_id=7;
	CHECK(bind_fake(&f)); CHECK(microlink_usb_guard_begin(5));
	CHECK(microlink_usb_open());
	init_fake(&f); f.close_in_open=1;
	CHECK(bind_fake(&f)); CHECK(microlink_usb_guard_begin(5));
	CHECK(!microlink_usb_open()); CHECK(f.close_calls==1 && !f.close_early);
	init_fake(&f); f.layout.output_report_id=256;
	CHECK(bind_fake(&f)); CHECK(microlink_usb_guard_begin(5));
	CHECK(!microlink_usb_open()); CHECK(strcmp(f.order,"INSORC")==0 && f.close_calls==1);
	return 0;
}

static int test_layout_after_open_failures(void)
{
	static fake_host_t f;
	init_fake(&f); f.layout_rc=-1;
	CHECK(bind_fake(&f)); CHECK(microlink_usb_guard_begin(5));
	CHECK(!microlink_usb_open()); CHECK(strcmp(f.order,"INSORC")==0);
	CHECK(f.close_calls==1 && f.read_calls==0 && f.write_calls==0);
	init_fake(&f); f.stop_in_layout=1;
	CHECK(bind_fake(&f)); CHECK(microlink_usb_guard_begin(5));
	CHECK(!microlink_usb_open()); CHECK(strcmp(f.order,"INSORC")==0);
	CHECK(f.close_calls==1 && f.read_calls==0 && f.write_calls==0);
	init_fake(&f); f.expire_in_layout=1;
	CHECK(bind_fake(&f)); CHECK(microlink_usb_guard_begin(5));
	CHECK(!microlink_usb_open()); CHECK(strcmp(f.order,"INSORC")==0);
	CHECK(f.close_calls==1 && f.read_calls==0 && f.write_calls==0);
	init_fake(&f); f.attempt_io_in_layout=1;
	CHECK(bind_fake(&f)); CHECK(microlink_usb_guard_begin(5));
	CHECK(!microlink_usb_open()); CHECK(f.io_rejected_in_layout);
	CHECK(f.close_calls==1 && f.read_calls==0 && f.write_calls==0);
	return 0;
}

static int test_init_failure_and_guard(void)
{
	static fake_host_t f; init_fake(&f); f.init_rc=-1;
	CHECK(bind_fake(&f)); CHECK(microlink_usb_guard_begin(5));
	CHECK(!microlink_usb_open()); CHECK(strcmp(f.order,"I")==0);
	init_fake(&f); CHECK(bind_fake(&f));
	CHECK(!microlink_usb_guard_begin(0)); CHECK(!microlink_usb_open());
	init_fake(&f); CHECK(bind_fake(&f));
	CHECK(microlink_usb_guard_begin(10)); f.now=1000;
	CHECK(microlink_usb_guard_begin(10)); f.now=10000;
	CHECK(microlink_usb_guard_expired());
	return 0;
}

static int test_write_framing(void)
{
	static fake_host_t f; unsigned char payload[63]; init_fake(&f); memset(payload,0x5a,sizeof(payload));
	CHECK(ready(&f)); CHECK(!microlink_usb_send_bytes(payload,0)); CHECK(f.write_calls==0);
	init_fake(&f); CHECK(ready(&f)); CHECK(!microlink_usb_send_bytes(payload,64)); CHECK(f.write_calls==0);
	init_fake(&f); CHECK(ready(&f)); CHECK(microlink_usb_send_bytes(payload,63));
	CHECK(f.writes_len==64 && f.writes[0]==8 && f.writes[1]==0x5a && f.writes[63]==0x5a);
	init_fake(&f); f.write_result=63; CHECK(ready(&f));
	CHECK(!microlink_usb_send_bytes(payload,1)); CHECK(f.write_calls==1);
	init_fake(&f); f.write_result=-1; CHECK(ready(&f));
	CHECK(!microlink_usb_send_bytes(payload,1)); CHECK(f.write_calls==1);
	CHECK(!microlink_usb_send_bytes(payload,1)); CHECK(f.write_calls==1);
	return 0;
}

static int test_read_boundaries_and_foreign(void)
{
	static fake_host_t f; unsigned char ch=0;
	init_fake(&f); CHECK(ready(&f)); queue_report(&f,7,63,0x44);
	CHECK(microlink_usb_get_char(&ch,0)<0);
	init_fake(&f); CHECK(ready(&f)); queue_report(&f,7,65,0x44);
	CHECK(microlink_usb_get_char(&ch,0)<0);
	init_fake(&f); CHECK(ready(&f)); queue_report(&f,7,64,0x44);
	CHECK(microlink_usb_get_char(&ch,2345)==1 && ch==0x44);
	CHECK(f.last_read_timeout==3);
	init_fake(&f); CHECK(ready(&f)); f.now=6000; queue_report(&f,7,64,0x44);
	CHECK(microlink_usb_get_char(&ch,20000000)==1 && ch==0x44);
	CHECK(f.last_read_timeout==4000);
	init_fake(&f); f.now=INT64_MAX-10000; CHECK(ready(&f));
	queue_report(&f,7,64,0x44);
	CHECK(microlink_usb_get_char(&ch,20000000)==1 && ch==0x44);
	CHECK(f.last_read_timeout==10000);
	init_fake(&f); CHECK(ready(&f)); queue_report(&f,9,64,0x33); queue_report(&f,7,64,0x22);
	CHECK(microlink_usb_get_char(&ch,10000)==1 && ch==0x22); CHECK(f.read_pos==2);
	init_fake(&f); CHECK(ready(&f)); queue_report(&f,9,3,0x33); queue_report(&f,9,5,0x33);
	queue_report(&f,7,64,0x22);
	CHECK(microlink_usb_get_char(&ch,10000)==1 && ch==0x22); CHECK(f.read_pos==3);
	init_fake(&f); CHECK(ready(&f)); f.advance_ms_each_read=5;
	queue_report(&f,9,64,0x33); queue_report(&f,7,64,0x22);
	CHECK(microlink_usb_get_char(&ch,10000)==1 && ch==0x22);
	CHECK(f.last_read_timeout==5);
	init_fake(&f); CHECK(ready(&f)); queue_report(&f,7,64,0);
	f.reads[0].bytes[2]=0x55;
	CHECK(microlink_usb_get_char(&ch,0)==1 && ch==0);
	CHECK(microlink_usb_drop_report_padding()==0);
	CHECK(microlink_usb_get_char(&ch,0)==1 && ch==0x55);
	return 0;
}

static int test_stop_deadline_clock_and_reentrant_close(void)
{
	static fake_host_t f; unsigned char ch=0;
	init_fake(&f); CHECK(ready(&f)); f.stop=1;
	CHECK(microlink_usb_get_char(&ch,0)<0); microlink_usb_close(); CHECK(f.close_calls==1);
	init_fake(&f); CHECK(ready(&f)); f.now=10000;
	CHECK(microlink_usb_get_char(&ch,0)<0); microlink_usb_close(); CHECK(f.close_calls==1);
	init_fake(&f); CHECK(ready(&f)); f.now=1000;
	CHECK(!microlink_usb_guard_expired()); f.rollback_clock=1;
	CHECK(microlink_usb_get_char(&ch,0)<0);
	init_fake(&f); CHECK(ready(&f)); f.stop_in_read=1; queue_report(&f,7,64,0x11);
	CHECK(microlink_usb_get_char(&ch,1000)<0); microlink_usb_close(); CHECK(f.close_calls==1);
	init_fake(&f); CHECK(ready(&f)); f.expire_in_read=1; queue_report(&f,7,64,0x11);
	CHECK(microlink_usb_get_char(&ch,1000)<0); microlink_usb_close(); CHECK(f.close_calls==1);
	init_fake(&f); CHECK(ready(&f)); f.clock_fail=1;
	CHECK(microlink_usb_get_char(&ch,1000)<0); CHECK(f.read_pos==0);
	init_fake(&f); CHECK(ready(&f)); queue_report(&f,7,64,0x11);
	CHECK(microlink_usb_get_char(&ch,1000)==1); f.now=10000;
	CHECK(microlink_usb_get_char(&ch,1000)<0);
	init_fake(&f); CHECK(ready(&f)); f.close_in_read=1; queue_report(&f,7,64,0x11);
	CHECK(microlink_usb_get_char(&ch,0)<0); CHECK(f.close_calls==1 && !f.close_early);
	init_fake(&f); CHECK(ready(&f)); f.close_in_write=1; { unsigned char b=1;
		CHECK(!microlink_usb_send_bytes(&b,1)); CHECK(f.close_calls==1 && !f.close_early); }
	return 0;
}

static int test_flush_close_and_fallback(void)
{
	static fake_host_t f; int ac=11,dis=12,below=13; long charge=14,runtime=15;
	init_fake(&f); CHECK(bind_fake(&f)); CHECK(microlink_usb_guard_begin(5));
	microlink_usb_flush_io(); CHECK(f.read_calls==0); CHECK(!microlink_usb_open());
	init_fake(&f); CHECK(ready(&f)); queue_report(&f,7,64,0x11);
	microlink_usb_flush_io(); CHECK(f.read_pos==1 && !microlink_usb_guard_expired());
	microlink_usb_close(); microlink_usb_close(); CHECK(f.close_calls==1);
	CHECK(microlink_usb_reset_and_reopen()==0);
	CHECK(microlink_usb_hid_fallback_supported()==0);
	CHECK(microlink_usb_get_hid_fallback(1,&ac,&dis,&below,&charge,&runtime)==0);
	CHECK(ac==11 && dis==12 && below==13 && charge==14 && runtime==15);
	init_fake(&f); CHECK(ready(&f));
	for (int i=0;i<40;i++) queue_report(&f,9,64,0x10);
	microlink_usb_flush_io(); CHECK(f.read_pos==32 && microlink_usb_guard_expired());
	return 0;
}

static int test_close_failure_retains_owner(void)
{
	static fake_host_t f; init_fake(&f); CHECK(ready(&f));
	f.close_rc=-1;
	microlink_usb_close(); CHECK(f.close_calls==1);
	microlink_usb_close(); CHECK(f.close_calls==1);
	CHECK(!bind_fake(&f));
	return 0;
}

static int diagnostic_equals(mlink_admission_stage_t stage,
	mlink_admission_reason_t reason, mlink_admission_parser_status_t parser_status)
{
	mlink_admission_diagnostic_t diagnostic = mlink_shared_admission_diagnostic();
	return diagnostic.stage == stage && diagnostic.reason == reason
		&& diagnostic.parser_status == parser_status;
}

static int rejected_diagnostic_falls_back(mlink_admission_stage_t failure_stage,
	mlink_admission_diagnostic_t supplied)
{
	static fake_host_t f;
	init_fake(&f);
	f.diagnostic = supplied;
	switch (failure_stage) {
	case MLINK_ADMISSION_STAGE_INIT: f.init_rc = -1; break;
	case MLINK_ADMISSION_STAGE_NONEXCLUSIVE: f.exclusive_rc = -1; break;
	case MLINK_ADMISSION_STAGE_OPEN: f.open_rc = -1; break;
	case MLINK_ADMISSION_STAGE_LAYOUT: f.layout_rc = -1; break;
	default: return 0;
	}
	if (!mlink_shared_test_bind(&ops,&f) || !microlink_usb_guard_begin(5)
	 || microlink_usb_open()) return 0;
	if (!diagnostic_equals(failure_stage, MLINK_ADMISSION_REASON_HOST_FAILED,
		MLINK_ADMISSION_PARSER_NOT_RUN) || f.diagnostic_calls != 1) return 0;
	return 1;
}

static int test_incoherent_host_diagnostics_fall_back(void)
{
	static const struct {
		mlink_admission_stage_t failure_stage;
		mlink_admission_diagnostic_t supplied;
	} cases[] = {
		{MLINK_ADMISSION_STAGE_INIT, {MLINK_ADMISSION_STAGE_INIT,
			MLINK_ADMISSION_REASON_OPEN_NULL, MLINK_ADMISSION_PARSER_NOT_RUN}},
		{MLINK_ADMISSION_STAGE_NONEXCLUSIVE, {MLINK_ADMISSION_STAGE_NONEXCLUSIVE,
			MLINK_ADMISSION_REASON_SELECTION_ZERO, MLINK_ADMISSION_PARSER_NOT_RUN}},
		{MLINK_ADMISSION_STAGE_OPEN, {MLINK_ADMISSION_STAGE_OPEN,
			MLINK_ADMISSION_REASON_ENTRY_LIMIT, MLINK_ADMISSION_PARSER_NOT_RUN}},
		{MLINK_ADMISSION_STAGE_LAYOUT, {MLINK_ADMISSION_STAGE_LAYOUT,
			MLINK_ADMISSION_REASON_PATH_INVALID, MLINK_ADMISSION_PARSER_NOT_RUN}},
		{MLINK_ADMISSION_STAGE_INIT, {MLINK_ADMISSION_STAGE_OPEN,
			MLINK_ADMISSION_REASON_OPEN_NULL, MLINK_ADMISSION_PARSER_NOT_RUN}},
		{MLINK_ADMISSION_STAGE_LAYOUT, {MLINK_ADMISSION_STAGE_LAYOUT,
			MLINK_ADMISSION_REASON_PARSER_REJECTED, MLINK_ADMISSION_PARSER_NOT_RUN}},
		{MLINK_ADMISSION_STAGE_LAYOUT, {MLINK_ADMISSION_STAGE_LAYOUT,
			MLINK_ADMISSION_REASON_LAYOUT_INVALID, MLINK_ADMISSION_PARSER_UNSUPPORTED}}
	};
	for (size_t i=0;i<sizeof(cases)/sizeof(cases[0]);i++) {
		CHECK(rejected_diagnostic_falls_back(cases[i].failure_stage, cases[i].supplied));
	}
	return 0;
}

static int test_admission_diagnostic_latching(void)
{
	static fake_host_t f;
	int diagnostic_calls;
	init_fake(&f);
	CHECK(diagnostic_equals(MLINK_ADMISSION_STAGE_NONE,
		MLINK_ADMISSION_REASON_NONE, MLINK_ADMISSION_PARSER_NOT_RUN));
	f.init_rc=-1;
	CHECK(mlink_shared_test_bind(&ops,&f)); CHECK(microlink_usb_guard_begin(5));
	CHECK(!microlink_usb_open());
	CHECK(diagnostic_equals(MLINK_ADMISSION_STAGE_INIT,
		MLINK_ADMISSION_REASON_HOST_FAILED, MLINK_ADMISSION_PARSER_NOT_RUN));
	diagnostic_calls=f.diagnostic_calls;
	for (int i=0;i<3;i++) CHECK(diagnostic_equals(MLINK_ADMISSION_STAGE_INIT,
		MLINK_ADMISSION_REASON_HOST_FAILED, MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(f.diagnostic_calls==diagnostic_calls);
	CHECK(!microlink_usb_open());
	CHECK(diagnostic_equals(MLINK_ADMISSION_STAGE_INIT,
		MLINK_ADMISSION_REASON_HOST_FAILED, MLINK_ADMISSION_PARSER_NOT_RUN));

	init_fake(&f); f.diagnostic=(mlink_admission_diagnostic_t){
		MLINK_ADMISSION_STAGE_SELECT, MLINK_ADMISSION_REASON_SELECTION_AMBIGUOUS,
		MLINK_ADMISSION_PARSER_NOT_RUN};
	f.select_rc=-1;
	CHECK(mlink_shared_test_bind(&ops,&f)); CHECK(microlink_usb_guard_begin(5));
	CHECK(!microlink_usb_open());
	CHECK(diagnostic_equals(MLINK_ADMISSION_STAGE_SELECT,
		MLINK_ADMISSION_REASON_SELECTION_AMBIGUOUS, MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(f.diagnostic_calls==1);

	init_fake(&f); f.init_rc=-1;
	CHECK(mlink_shared_test_bind(&legacy_ops,&f)); CHECK(microlink_usb_guard_begin(5));
	CHECK(!microlink_usb_open());
	CHECK(diagnostic_equals(MLINK_ADMISSION_STAGE_INIT,
		MLINK_ADMISSION_REASON_HOST_FAILED, MLINK_ADMISSION_PARSER_NOT_RUN));

	init_fake(&f); CHECK(ready(&f));
	CHECK(diagnostic_equals(MLINK_ADMISSION_STAGE_NONE,
		MLINK_ADMISSION_REASON_NONE, MLINK_ADMISSION_PARSER_NOT_RUN));
	f.stop=1;
	{ unsigned char ch=0; CHECK(microlink_usb_get_char(&ch,0)<0); }
	CHECK(diagnostic_equals(MLINK_ADMISSION_STAGE_NONE,
		MLINK_ADMISSION_REASON_NONE, MLINK_ADMISSION_PARSER_NOT_RUN));
	return 0;
}

int main(void)
{
	int (*tests[])(void)={test_open_order_and_layout,test_open_rejections,
		test_layout_after_open_failures,
		test_init_failure_and_guard,test_write_framing,test_read_boundaries_and_foreign,
		test_stop_deadline_clock_and_reentrant_close,test_flush_close_and_fallback,
		test_admission_diagnostic_latching,test_incoherent_host_diagnostics_fall_back,
		test_close_failure_retains_owner};
	size_t i;
	if (microlink_usb_guard_expired() != 0) return 1;
	if (microlink_usb_open() != 0) return 1;
	for (i=0;i<sizeof(tests)/sizeof(tests[0]);i++) {
		if (tests[i]()!=0) return 1;
		mlink_shared_test_unbind();
	}
	puts("PASS synthetic shared transport cases=11");
	return 0;
}
#endif
