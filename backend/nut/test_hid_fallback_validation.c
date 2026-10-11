/* SPDX-License-Identifier: GPL-2.0-or-later
 * Synthetic offline checks for complete HID fields and clock rollback. */
#include <limits.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#if WITH_USB != 1 || WITH_LIBUSB_1_0 != 0 || defined(HAVE_PTHREAD)
#error "validation harness must remain synthetic and non-concurrent"
#endif

static time_t replay_time;
static unsigned int clock_reads;
static unsigned int failures;

static void check(int condition, const char *name)
{
	if (!condition) {
		printf("FAIL %s\n", name);
		failures++;
	}
}

static time_t microlink_now(void)
{
	clock_reads++;
	return replay_time;
}

enum { EVENT_DSTATE = 1, EVENT_STATUS_INIT, EVENT_STATUS_TOKEN, EVENT_STATUS_COMMIT };
typedef struct { int kind; char name[96]; char value[96]; } replay_event_t;
static replay_event_t events[32];
static size_t event_count;
static int is_usb = 1;
static int hid_fallback_enabled = 1;

static void record_event(int kind, const char *name, const char *value)
{
	if (event_count >= sizeof(events) / sizeof(events[0])) {
		failures++;
		return;
	}
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

static void status_init(void) { record_event(EVENT_STATUS_INIT, "", ""); }
static void status_set(const char *token) { record_event(EVENT_STATUS_TOKEN, token, ""); }
static void status_commit(void) { record_event(EVENT_STATUS_COMMIT, "", ""); }

#include "hid_fallback_validation_generated.c"

static int has_token(const char *token)
{
	size_t i;
	for (i = 0; i < event_count; i++) {
		if (events[i].kind == EVENT_STATUS_TOKEN && strcmp(events[i].name, token) == 0) {
			return 1;
		}
	}
	return 0;
}

static void reset_events(void)
{
	memset(events, 0, sizeof(events));
	event_count = 0;
}

static void reset_fixture(void)
{
	replay_reset_fallback_state();
	memset(&ff_charging, 0, sizeof(ff_charging));
	memset(&ff_discharging, 0, sizeof(ff_discharging));
	memset(&ff_ac_present, 0, sizeof(ff_ac_present));
	memset(&ff_below_rcl, 0, sizeof(ff_below_rcl));
	memset(&ff_remaining_capacity, 0, sizeof(ff_remaining_capacity));
	memset(&ff_runtime_to_empty, 0, sizeof(ff_runtime_to_empty));
	fb_ac_present = fb_discharging = fb_below_rcl = 0;
	fb_battery_charge = fb_battery_runtime = -1;
	fb_ac_present_update = fb_discharging_update = 0;
	ff_ac_present = (hid_fallback_field_t){1, 0, 1};
	ff_discharging = (hid_fallback_field_t){2, 0, 1};
	ff_below_rcl = (hid_fallback_field_t){3, 0, 1};
	ff_remaining_capacity = (hid_fallback_field_t){4, 0, 8};
	ff_runtime_to_empty = (hid_fallback_field_t){5, 0, 8};
	replay_time = 100;
	clock_reads = 0;
	is_usb = hid_fallback_enabled = 1;
	reset_events();
}

static void send_bytes(int report_id, const unsigned char *payload, size_t length, time_t at)
{
	unsigned char report[66];
	if (length + 1 > sizeof(report)) {
		failures++;
		return;
	}
	report[0] = (unsigned char)report_id;
	if (length != 0) {
		memcpy(report + 1, payload, length);
	}
	replay_time = at;
	microlink_usb_try_decode_fallback(report, length + 1);
}

static void send_byte(int report_id, unsigned char value, time_t at)
{
	send_bytes(report_id, &value, 1, at);
}

static int get_snapshot(int max_age, time_t at, int *ac, int *discharging)
{
	replay_time = at;
	clock_reads = 0;
	return microlink_usb_get_hid_fallback(max_age, ac, discharging, NULL, NULL, NULL);
}

static void test_incomplete_and_straddled_fields(void)
{
	unsigned char one = 1;
	unsigned char two[] = {1, 1};
	int ac = 77, discharging = 88;
	reset_fixture();
	ff_ac_present = (hid_fallback_field_t){7, 0, 1};
	ff_discharging = (hid_fallback_field_t){7, 8, 1};
	send_bytes(7, NULL, 0, 110); /* ID-only */
	check(!get_snapshot(30, 110, &ac, &discharging), "incomplete report ID-only unavailable");
	check(ac == 77 && discharging == 88, "failed getter leaves outputs untouched");
	send_bytes(7, &one, 1, 111); /* AC complete, discharging absent */
	check(fb_ac_present == 1 && fb_ac_present_update == 111, "complete field updates independently");
	check(fb_discharging_update == 0, "incomplete sibling does not refresh cache");
	check(!get_snapshot(30, 111, &ac, &discharging), "incomplete sibling keeps pair unavailable");
	send_bytes(7, two, sizeof(two), 112);
	check(get_snapshot(30, 112, &ac, &discharging), "complete straddled report makes pair available");
	check(ac == 1 && discharging == 1, "straddled field values extracted");
	send_bytes(7, two, sizeof(two), 113);
	one = 0;
	send_bytes(7, &one, 1, 119);
	check(fb_discharging == 1 && fb_discharging_update == 113,
		"incomplete report preserves prior status cache and timestamp");
	check(!get_snapshot(5, 119, &ac, &discharging), "incomplete report cannot refresh prior status pair");
}

static void test_report_id_and_invalid_metadata(void)
{
	int ac = 0, discharging = 0;
	reset_fixture();
	send_byte(9, 1, 120);
	send_byte(0, 1, 121);
	check(fb_ac_present_update == 0 && fb_discharging_update == 0, "wrong and zero IDs ignored");
	check(!get_snapshot(30, 121, &ac, &discharging), "wrong and zero IDs unavailable");

#if VALIDATION_CANDIDATE
	{
		hid_fallback_field_t invalid[] = {
			{7, 0, 0}, {7, 0, 33}, {7, -1, 1}, {7, INT_MAX, 1}, {0, 0, 1}
		};
		size_t i;
		for (i = 0; i < sizeof(invalid) / sizeof(invalid[0]); i++) {
			check(!hid_field_fits_report(&invalid[i], 66), "invalid field metadata rejected");
		}
	}
#endif

	reset_fixture();
	ff_remaining_capacity = (hid_fallback_field_t){4, 0, 8};
	ff_runtime_to_empty = (hid_fallback_field_t){4, 8, 8};
	send_bytes(4, NULL, 0, 129);
	check(fb_battery_charge == -1 && fb_battery_runtime == -1,
		"ID-only optional report preserves neutral missing values");
	send_byte(4, 73, 130);
	check(fb_battery_charge == 73 && fb_battery_runtime == -1,
		"complete optional field updates independently");
	{
		unsigned char both[] = {73, 180};
		send_bytes(4, both, sizeof(both), 131);
	}
	check(fb_battery_charge == 73 && fb_battery_runtime == 180,
		"complete optional fields are cached");

	ff_remaining_capacity = (hid_fallback_field_t){4, 7, 2};
	{
		unsigned char partial = 0x80;
		unsigned char complete[] = {0x80, 0x01};
		send_bytes(4, &partial, 1, 132);
		check(fb_battery_charge == 73, "partial straddling optional field preserves cache");
		send_bytes(4, complete, sizeof(complete), 133);
		check(fb_battery_charge == 3, "two-bit field crossing byte boundary extracts fully");
	}

	ff_remaining_capacity = (hid_fallback_field_t){4, 0, 32};
	{
		unsigned char short_value[] = {1, 2, 3};
		unsigned char full_value[] = {0x11, 0x22, 0x33, 0x44};
		send_bytes(4, short_value, sizeof(short_value), 134);
		check(fb_battery_charge == 3, "32-bit partial report preserves cache");
		send_bytes(4, full_value, sizeof(full_value), 135);
		check(fb_battery_charge == 0x44332211L, "complete 32-bit field extracts");
	}
	{
		long runtime = 999;
		long previous_runtime = fb_battery_runtime;
		ff_runtime_to_empty = (hid_fallback_field_t){0, 0, 8};
		check(fb_battery_runtime == previous_runtime, "absent optional descriptor retains prior cache");
		send_byte(1, 1, 140);
		send_byte(2, 0, 140);
		check(microlink_usb_get_hid_fallback(30, NULL, NULL, NULL, NULL, &runtime)
			&& runtime == -1, "absent optional runtime is returned as neutral");
	}
}

static void test_age_boundary_and_clock_rollback(void)
{
	int ac = 77, discharging = 88;
	reset_fixture();
	send_byte(1, 1, 200);
	send_byte(2, 0, 200);
	check(get_snapshot(0, 200, &ac, &discharging), "age zero accepts same instant");
	#if VALIDATION_CANDIDATE
	check(clock_reads == 1, "getter samples wall clock once");
	#endif
	check(get_snapshot(30, 230, &ac, &discharging), "inclusive age boundary accepted");
	check(!get_snapshot(30, 231, &ac, &discharging), "stale first second rejected");
	check(!get_snapshot(-1, 200, &ac, &discharging), "negative max age rejected");

	reset_fixture();
	send_byte(1, 1, 300);
	send_byte(2, 0, 300);
	ac = 77;
	discharging = 88;
	check(!get_snapshot(30, 299, &ac, &discharging), "rollback invalidates pair");
	check(fb_ac_present_update == 0 && fb_discharging_update == 0, "rollback clears both timestamps");
	check(ac == 77 && discharging == 88, "rollback leaves caller outputs untouched");
	check(!get_snapshot(30, 330, &ac, &discharging), "catch-up cannot resurrect old pair");
	send_byte(1, 1, 330);
	check(!get_snapshot(30, 330, &ac, &discharging), "one new status report is insufficient");
	send_byte(2, 0, 330);
	check(get_snapshot(30, 330, &ac, &discharging), "new pair recovers after rollback");
}

static void test_publisher_and_status_mappings(void)
{
	reset_fixture();
	ff_ac_present = (hid_fallback_field_t){7, 0, 1};
	ff_discharging = (hid_fallback_field_t){7, 1, 1};
	send_bytes(7, NULL, 0, 400);
	check(!microlink_publish_hid_fallback(), "publisher suppresses invalid status");
	check(event_count == 0, "invalid fallback emits no events");

	reset_fixture();
	send_byte(1, 1, 405);
	send_byte(2, 0, 405);
	replay_time = 404;
	check(!microlink_publish_hid_fallback(), "publisher suppresses status after rollback");
	check(event_count == 0, "rollback emits no publisher events");

	reset_fixture();
	send_byte(1, 1, 410);
	send_byte(2, 0, 410);
	check(microlink_publish_hid_fallback() && has_token("OL"), "positive online mapping");

	reset_fixture();
	send_byte(1, 0, 420);
	send_byte(2, 1, 420);
	check(microlink_publish_hid_fallback() && has_token("OB"), "positive on-battery mapping");
}

int main(void)
{
	test_incomplete_and_straddled_fields();
	test_report_id_and_invalid_metadata();
	test_age_boundary_and_clock_rollback();
	test_publisher_and_status_mappings();
	if (failures != 0) {
		printf("%u validation check(s) failed\n", failures);
		return 1;
	}
	puts("all HID fallback validation checks passed");
	return 0;
}
