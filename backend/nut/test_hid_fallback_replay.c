/* SPDX-License-Identifier: GPL-2.0-or-later
 * Synthetic replay against exact NUT fallback excerpts, never USB hardware. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#if WITH_LIBUSB_1_0 != 0
#error "fallback replay must compile with WITH_LIBUSB_1_0=0"
#endif
#if defined(HAVE_PTHREAD)
#error "fallback replay excludes pthread/concurrent qualification"
#endif
#if REPLAY_EXPECT_FIX != 0 && REPLAY_EXPECT_FIX != 1
#error "REPLAY_EXPECT_FIX must be 0 or 1"
#endif

static time_t replay_time;

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
	replay_time = 100;
	ff_ac_present = (hid_fallback_field_t){1, 0, 1};
	ff_discharging = (hid_fallback_field_t){2, 0, 1};
	ff_below_rcl = (hid_fallback_field_t){3, 0, 1};
	ff_remaining_capacity = (hid_fallback_field_t){4, 0, 8};
	ff_runtime_to_empty = (hid_fallback_field_t){5, 0, 8};
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

static void test_initial_and_charge_runtime_first(void)
{
	snapshot_t result;
	fixture_reset();
	result = read_snapshot(30, 100);
	assert(!result.available);

	send_report(4, 82, 101);
	send_report(5, 180, 102);
	result = read_snapshot(30, 102);
#if REPLAY_EXPECT_FIX
	assert(!result.available);
#else
	assert(result.available);
	assert(result.ac_present == 0 && result.discharging == 0);
	assert(result.charge == 82 && result.runtime == 180);
	puts("BASE REPRO: charge/runtime alone refresh zero-default status fields");
#endif
}

static void test_partial_then_both_status_fields(void)
{
	snapshot_t result;
	fixture_reset();
	send_report(1, 1, 200);
	result = read_snapshot(30, 200);
#if REPLAY_EXPECT_FIX
	assert(!result.available);
#else
	assert(result.available);
	assert(result.ac_present == 1 && result.discharging == 0);
	puts("BASE REPRO: one status field makes the shared snapshot publishable");
#endif

	send_report(2, 0, 201);
	result = read_snapshot(30, 201);
	assert(result.available);
	assert(result.ac_present == 1 && result.discharging == 0);
}

static void test_charge_cannot_keep_old_status_fresh(void)
{
	snapshot_t result;
	fixture_reset();
	send_report(1, 1, 300);
	send_report(2, 0, 300);
	send_report(4, 75, 300);

	result = read_snapshot(30, 330);
	assert(result.available); /* exact age boundary is inclusive upstream */

	send_report(4, 74, 331);
	result = read_snapshot(30, 331);
#if REPLAY_EXPECT_FIX
	assert(!result.available);
#else
	assert(result.available);
	assert(result.ac_present == 1 && result.discharging == 0);
	puts("BASE REPRO: fresh charge masks stale AC/discharging status");
#endif
}

static void test_status_freshness_is_independent_each_direction(void)
{
	snapshot_t result;
	fixture_reset();
	send_report(1, 1, 800);
	send_report(2, 0, 800);
	send_report(1, 0, 831);
	result = read_snapshot(30, 831);
#if REPLAY_EXPECT_FIX
	assert(!result.available); /* fresh AC must not refresh stale discharging */
#else
	assert(result.available);
	puts("BASE REPRO: fresh AC masks stale discharging status");
#endif

	fixture_reset();
	send_report(1, 1, 800);
	send_report(2, 0, 800);
	send_report(2, 1, 831);
	result = read_snapshot(30, 831);
#if REPLAY_EXPECT_FIX
	assert(!result.available); /* fresh discharging must not refresh stale AC */
#else
	assert(result.available);
	puts("BASE REPRO: fresh discharging masks stale AC status");
#endif
}

static void test_synthetic_on_battery_values(void)
{
	snapshot_t result;
	fixture_reset();
	send_report(1, 0, 400);
	send_report(2, 1, 400);
	result = read_snapshot(30, 400);
	assert(result.available);
	assert(result.ac_present == 0 && result.discharging == 1);
	puts("SYNTHETIC ONLY: fresh values encode absent AC plus discharging");
}

static void test_negative_and_stale_ages(void)
{
	snapshot_t result;
	fixture_reset();
	send_report(1, 1, 500);
	send_report(2, 0, 500);
	result = read_snapshot(-1, 500);
	assert(!result.available);
	result = read_snapshot(30, 530);
	assert(result.available);
	result = read_snapshot(30, 531);
	assert(!result.available);
}

static void test_truncated_status_report_residual(void)
{
	snapshot_t result;
	fixture_reset();
	ff_ac_present = (hid_fallback_field_t){7, 0, 1};
	ff_discharging = (hid_fallback_field_t){7, 1, 1};
	send_truncated_report(7, 600);
	result = read_snapshot(30, 600);
	assert(result.available);
	assert(result.ac_present == 0 && result.discharging == 0);
	puts("RESIDUAL: truncated status report can refresh zero-extracted fields");
}

static void test_wall_clock_rollback_residual(void)
{
	snapshot_t result;
	fixture_reset();
	send_report(1, 1, 700);
	send_report(2, 0, 700);
	result = read_snapshot(30, 699);
	assert(result.available);
	puts("RESIDUAL: wall-clock rollback is treated as fresh by difftime check");
}

int main(void)
{
	test_initial_and_charge_runtime_first();
	test_partial_then_both_status_fields();
	test_charge_cannot_keep_old_status_fresh();
	test_status_freshness_is_independent_each_direction();
	test_synthetic_on_battery_values();
	test_negative_and_stale_ages();
	test_truncated_status_report_residual();
	test_wall_clock_rollback_residual();
	puts(REPLAY_EXPECT_FIX ? "FIXED-COMMIT REPLAY: PASS" : "BASE-COMMIT REPLAY: PASS");
	return 0;
}
