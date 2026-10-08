/* SPDX-License-Identifier: GPL-2.0-or-later
 * Synthetic replay against exact NUT fallback and publisher excerpts. */
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#if WITH_USB != 1
#error "publisher replay must compile with WITH_USB=1"
#endif
#if WITH_LIBUSB_1_0 != 0
#error "fallback replay must compile with WITH_LIBUSB_1_0=0"
#endif
#if defined(HAVE_PTHREAD)
#error "fallback replay excludes pthread/concurrent qualification"
#endif
#if REPLAY_EXPECT_FIX != 0 && REPLAY_EXPECT_FIX != 1
#error "REPLAY_EXPECT_FIX must be 0 or 1"
#endif

enum {
	EVENT_DSTATE = 1,
	EVENT_STATUS_INIT,
	EVENT_STATUS_TOKEN,
	EVENT_STATUS_COMMIT
};

typedef struct {
	int kind;
	char name[96];
	char value[96];
} replay_event_t;

static replay_event_t events[32];
static size_t event_count;
static int is_usb = 1;
static int hid_fallback_enabled = 1;
static time_t replay_time;

static void record_event(int kind, const char *name, const char *value)
{
	assert(event_count < sizeof(events) / sizeof(events[0]));
	events[event_count].kind = kind;
	snprintf(events[event_count].name, sizeof(events[event_count].name), "%s", name ? name : "");
	snprintf(events[event_count].value, sizeof(events[event_count].value), "%s", value ? value : "");
	event_count++;
}

static void dstate_setinfo(const char *name, const char *format, ...)
{
	char value[96];
	va_list arguments;
	va_start(arguments, format);
	vsnprintf(value, sizeof(value), format, arguments);
	va_end(arguments);
	record_event(EVENT_DSTATE, name, value);
}

static void status_init(void)
{
	record_event(EVENT_STATUS_INIT, "", "");
}

static void status_set(const char *token)
{
	record_event(EVENT_STATUS_TOKEN, token, "");
}

static void status_commit(void)
{
	record_event(EVENT_STATUS_COMMIT, "", "");
}

static time_t microlink_now(void)
{
	return replay_time;
}

#include "hid_fallback_replay_generated.c"

typedef struct {
	int available;
	int ac_present;
	int discharging;
	int below_rcl;
	long charge;
	long runtime;
} snapshot_t;

static int event_index(int kind, const char *name, const char *value)
{
	size_t index;
	for (index = 0; index < event_count; index++) {
		if (events[index].kind == kind
		&& (!name || strcmp(events[index].name, name) == 0)
		&& (!value || strcmp(events[index].value, value) == 0)) {
			return (int)index;
		}
	}
	return -1;
}

static int has_status_token(const char *token)
{
	return event_index(EVENT_STATUS_TOKEN, token, NULL) >= 0;
}

static void clear_events(void)
{
	memset(events, 0, sizeof(events));
	event_count = 0;
}

static void install_layout(void)
{
	ff_ac_present = (hid_fallback_field_t){1, 0, 1};
	ff_discharging = (hid_fallback_field_t){2, 0, 1};
	ff_below_rcl = (hid_fallback_field_t){3, 0, 1};
	ff_remaining_capacity = (hid_fallback_field_t){4, 0, 8};
	ff_runtime_to_empty = (hid_fallback_field_t){5, 0, 8};
}

static void fixture_reset(void)
{
	memset(&ff_charging, 0, sizeof(ff_charging));
	memset(&ff_discharging, 0, sizeof(ff_discharging));
	memset(&ff_ac_present, 0, sizeof(ff_ac_present));
	memset(&ff_below_rcl, 0, sizeof(ff_below_rcl));
	memset(&ff_remaining_capacity, 0, sizeof(ff_remaining_capacity));
	memset(&ff_runtime_to_empty, 0, sizeof(ff_runtime_to_empty));
	fb_ac_present = 0;
	fb_discharging = 0;
	fb_below_rcl = 0;
	fb_battery_charge = -1;
	fb_battery_runtime = -1;
#if REPLAY_EXPECT_FIX
	fb_ac_present_update = 0;
	fb_discharging_update = 0;
#else
	fb_last_update = 0;
#endif
	mlink_report_out = 0;
	mlink_report_in = 0;
	is_usb = 1;
	hid_fallback_enabled = 1;
	replay_time = 100;
	clear_events();
	install_layout();
}

static void send_report(int report_id, unsigned char value, time_t at)
{
	unsigned char report[] = {(unsigned char)report_id, value};
	replay_time = at;
	microlink_usb_try_decode_fallback(report, sizeof(report));
}

static void send_truncated_report(int report_id, time_t at)
{
	unsigned char report[] = {(unsigned char)report_id};
	replay_time = at;
	microlink_usb_try_decode_fallback(report, sizeof(report));
}

static snapshot_t read_snapshot(int max_age_sec, time_t at)
{
	snapshot_t result = {0, -1, -1, -1, -99, -99};
	replay_time = at;
	result.available = microlink_usb_get_hid_fallback(
		max_age_sec,
		&result.ac_present,
		&result.discharging,
		&result.below_rcl,
		&result.charge,
		&result.runtime);
	return result;
}

static void expect_unpublished(void)
{
	assert(!microlink_publish_hid_fallback());
	assert(event_count == 0);
}

static void test_mapper_guards(void)
{
	fixture_reset();
	send_report(1, 1, 100);
	send_report(2, 0, 100);
	is_usb = 0;
	expect_unpublished();
	is_usb = 1;
	hid_fallback_enabled = 0;
	expect_unpublished();
}

static void test_charge_runtime_without_status(void)
{
	fixture_reset();
	send_report(4, 82, 101);
	send_report(5, 180, 102);
#if REPLAY_EXPECT_FIX
	expect_unpublished();
#else
	assert(microlink_publish_hid_fallback());
	assert(has_status_token("OB"));
	puts("BASE REPRO: charge/runtime alone publish default-zero OB through mapper");
#endif
}

static void test_one_status_then_both(void)
{
	fixture_reset();
	send_report(1, 1, 200);
#if REPLAY_EXPECT_FIX
	expect_unpublished();
#else
	assert(microlink_publish_hid_fallback());
	assert(has_status_token("OL"));
	puts("BASE REPRO: one status flag maps default discharging to OL");
#endif
	send_report(2, 0, 201);
	clear_events();
	assert(microlink_publish_hid_fallback());
	assert(has_status_token("OL"));
}

static void test_online_and_on_battery_mapping_and_order(void)
{
	fixture_reset();
	send_report(1, 1, 300);
	send_report(2, 0, 300);
	send_report(3, 0, 300);
	send_report(4, 74, 300);
	send_report(5, 180, 300);
	assert(microlink_publish_hid_fallback());
	assert(event_index(EVENT_DSTATE, "battery.charge", "74") == 0);
	assert(event_index(EVENT_DSTATE, "battery.runtime", "180") == 1);
	assert(event_index(EVENT_STATUS_INIT, NULL, NULL) == 2);
	assert(event_index(EVENT_STATUS_TOKEN, "OL", NULL) == 3);
	assert(event_index(EVENT_STATUS_TOKEN, "CHRG", NULL) == 4);
	assert(event_index(EVENT_STATUS_COMMIT, NULL, NULL) == 5);
	assert(event_index(EVENT_DSTATE, "experimental.microlink.diag.hid_fallback.active", "1") == 6);

	fixture_reset();
	send_report(1, 0, 400);
	send_report(2, 1, 400);
	send_report(4, 50, 400);
	assert(microlink_publish_hid_fallback());
	assert(has_status_token("OB"));
	assert(has_status_token("DISCHRG"));
}

static void test_missing_and_expired_status_do_not_publish(void)
{
	snapshot_t snapshot;
	fixture_reset();
	expect_unpublished();
	send_report(1, 1, 500);
	send_report(2, 0, 500);
	snapshot = read_snapshot(MLINK_HID_FALLBACK_MAX_AGE_SEC, 530);
	assert(snapshot.available); /* inclusive max-age boundary */
	replay_time = 530;
	assert(microlink_publish_hid_fallback());
	assert(has_status_token("OL"));
	clear_events();
	replay_time = 531;
	expect_unpublished(); /* first stale second with no intervening reports */

	send_report(4, 82, 530);
	send_report(5, 180, 530);
	snapshot = read_snapshot(MLINK_HID_FALLBACK_MAX_AGE_SEC, 531);
#if REPLAY_EXPECT_FIX
	assert(!snapshot.available); /* charge/runtime do not refresh status */
	expect_unpublished();
#else
	assert(snapshot.available);
	clear_events();
	assert(microlink_publish_hid_fallback());
	assert(has_status_token("OL"));
	puts("BASE REPRO: fresh charge/runtime masks stale status");
#endif
}

static void test_independent_status_freshness_directions(void)
{
	snapshot_t snapshot;
	fixture_reset();
	send_report(1, 1, 800);
	send_report(2, 0, 800);
	send_report(1, 0, 831);
	snapshot = read_snapshot(MLINK_HID_FALLBACK_MAX_AGE_SEC, 831);
#if REPLAY_EXPECT_FIX
	assert(!snapshot.available); /* fresh AC cannot refresh stale discharging */
	expect_unpublished();
#else
	assert(snapshot.available);
	assert(microlink_publish_hid_fallback());
	assert(event_count > 0);
	puts("BASE REPRO: fresh AC masks stale discharging status");
#endif

	fixture_reset();
	send_report(1, 1, 900);
	send_report(2, 0, 900);
	send_report(2, 1, 931);
	snapshot = read_snapshot(MLINK_HID_FALLBACK_MAX_AGE_SEC, 931);
#if REPLAY_EXPECT_FIX
	assert(!snapshot.available); /* fresh discharging cannot refresh stale AC */
	clear_events();
	expect_unpublished();
#else
	assert(snapshot.available);
	clear_events();
	assert(microlink_publish_hid_fallback());
	assert(event_count > 0);
	puts("BASE REPRO: fresh discharging masks stale AC status");
#endif
}

static void test_negative_age_and_stale_boundary(void)
{
	snapshot_t snapshot;
	fixture_reset();
	send_report(1, 1, 1000);
	send_report(2, 0, 1000);
	snapshot = read_snapshot(-1, 1000);
	assert(!snapshot.available);
	snapshot = read_snapshot(MLINK_HID_FALLBACK_MAX_AGE_SEC, 1030);
	assert(snapshot.available);
	snapshot = read_snapshot(MLINK_HID_FALLBACK_MAX_AGE_SEC, 1031);
	assert(!snapshot.available);
}

static void test_truncated_report_and_clock_rollback_residuals(void)
{
	snapshot_t snapshot;
	fixture_reset();
	ff_ac_present = (hid_fallback_field_t){7, 0, 1};
	ff_discharging = (hid_fallback_field_t){7, 1, 1};
	send_truncated_report(7, 600);
	snapshot = read_snapshot(MLINK_HID_FALLBACK_MAX_AGE_SEC, 600);
	assert(snapshot.available && snapshot.ac_present == 0 && snapshot.discharging == 0);
	clear_events();
	assert(microlink_publish_hid_fallback());
	assert(has_status_token("OB"));
	puts("RESIDUAL: truncated status report maps zero-extracted fields to OB");

	fixture_reset();
	send_report(1, 1, 700);
	send_report(2, 0, 700);
	replay_time = 699;
	clear_events();
	assert(microlink_publish_hid_fallback());
	assert(has_status_token("OL"));
	puts("RESIDUAL: backward wall-clock step publishes old status as fresh");
}

static void seed_old_session(time_t at)
{
	send_report(1, 1, at);
	send_report(2, 0, at);
	send_report(3, 1, at);
	send_report(4, 87, at);
	send_report(5, 210, at);
}

static void test_callback_reset_wrapper_and_layout_reinstall(void)
{
	fixture_reset();
	seed_old_session(800);
	ff_charging = (hid_fallback_field_t){6, 2, 1};
	mlink_report_out = 9;
	mlink_report_in = 10;
	assert(fb_ac_present == 1 && fb_discharging == 0 && fb_below_rcl == 1);
	assert(ff_ac_present.report_id != 0 && ff_discharging.report_id != 0);

	replay_reset_fallback_state();
	assert(mlink_report_out == 0 && mlink_report_in == 0);
	assert(ff_charging.report_id == 0 && ff_charging.offset == 0 && ff_charging.size == 0);
	assert(ff_discharging.report_id == 0 && ff_discharging.offset == 0 && ff_discharging.size == 0);
	assert(ff_ac_present.report_id == 0 && ff_ac_present.offset == 0 && ff_ac_present.size == 0);
	assert(ff_below_rcl.report_id == 0 && ff_below_rcl.offset == 0 && ff_below_rcl.size == 0);
	assert(ff_remaining_capacity.report_id == 0 && ff_remaining_capacity.offset == 0 && ff_remaining_capacity.size == 0);
	assert(ff_runtime_to_empty.report_id == 0 && ff_runtime_to_empty.offset == 0 && ff_runtime_to_empty.size == 0);
#if REPLAY_EXPECT_FIX
	assert(fb_ac_present_update == 0 && fb_discharging_update == 0);
	assert(fb_below_rcl == 0 && fb_battery_charge == -1 && fb_battery_runtime == -1);
#else
	assert(fb_last_update == 0);
	assert(fb_below_rcl == 1 && fb_battery_charge == 87 && fb_battery_runtime == 210);
#endif
	expect_unpublished(); /* descriptors are absent until the caller rebuilds layout */
	install_layout();
	expect_unpublished();
	send_report(4, 88, 801);
	send_report(5, 211, 802);
#if REPLAY_EXPECT_FIX
	expect_unpublished();
#else
	clear_events();
	assert(microlink_publish_hid_fallback());
	assert(has_status_token("OL"));
	puts("BASE REPRO: charge/runtime after reset revalidate retained status");
#endif
	clear_events();
	send_report(1, 1, 803);
	send_report(2, 0, 803);
	assert(microlink_publish_hid_fallback());
	assert(has_status_token("OL"));
}

int main(void)
{
	test_mapper_guards();
	test_charge_runtime_without_status();
	test_one_status_then_both();
	test_online_and_on_battery_mapping_and_order();
	test_missing_and_expired_status_do_not_publish();
	test_independent_status_freshness_directions();
	test_negative_age_and_stale_boundary();
	test_truncated_report_and_clock_rollback_residuals();
	test_callback_reset_wrapper_and_layout_reinstall();
	puts(REPLAY_EXPECT_FIX ? "FIXED-COMMIT CALLER REPLAY: PASS" : "BASE-COMMIT CALLER REPLAY: PASS");
	return 0;
}
