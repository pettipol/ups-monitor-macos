/* SPDX-License-Identifier: GPL-2.0-or-later
 * Synthetic symbols implement the authentic pinned HIDAPI declarations.
 * The LINK_ONLY build must never be executed by the replay runner.
 */
#include "apcmicrolink-hidapi-native.h"
#include "apcmicrolink-hid-descriptor-checked.h"
#include "apcmicrolink-hidapi-session.h"

#ifdef MLINK_HIDAPI_NATIVE_LINK_ONLY
int main(void) { return 0; }
#if defined(MLINK_HIDAPI_OPERATIONAL_V2)
int mlink_shared_cleanup_stop_write_authorized(void *user)
{
	(void)user;
	return 0;
}
#endif
#else

#include <apcmicrolink-usb.h>
#include <hidapi.h>
#include <hidapi_darwin.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#define CHECK(expr) do { if (!(expr)) { \
	fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #expr); return 1; \
} } while (0)

#define SYNTHETIC_VID 0x1234U
#define SYNTHETIC_PID 0x5678U

struct hid_device_ { int synthetic; };
static struct hid_device_ device = {1};
static const unsigned char valid_descriptor[] = {
	0x06,0x86,0xff,0x09,0x01,0xa1,0x01,
	0x85,0x07,0x09,0xfd,0x75,0x08,0x95,0x3f,0x81,0x02,
	0x85,0x08,0x09,0xfc,0x75,0x08,0x95,0x3f,0x91,0x02,0xc0
};

typedef struct fake_hidapi {
	char order[128];
	size_t order_len;
	int init_rc, exit_rc, setter_ignored, exclusive, device_exclusive;
	int stop, stop_in_open, io_in_descriptor, io_rejected;
	int open_fail, descriptor_error;
	int enumerate_calls, free_calls, open_calls, close_calls, descriptor_calls;
	int read_calls, write_calls, exit_calls, calls_outside_contract;
	unsigned short enumerated_vid, enumerated_pid;
	struct hid_device_info entries[1025];
	struct hid_device_info *enumeration;
	unsigned char descriptor[MLINK_HID_DESC_MAX_BYTES + 2U];
	size_t descriptor_length, descriptor_capacity;
	int read_result, write_result;
	size_t read_capacity, write_length;
	int read_timeout;
	unsigned char written[64];
	int write_advance_seconds;
	int clock_rc, stop_calls, clock_calls;
	struct timespec now;
} fake_hidapi_t;

static fake_hidapi_t fake;

static void mark(char ch)
{
	if (fake.order_len + 1 < sizeof(fake.order)) {
		fake.order[fake.order_len++] = ch;
		fake.order[fake.order_len] = '\0';
	}
}

int hid_init(void)
{
	mark('I');
	if (fake.init_rc == 0) fake.exclusive = 1;
	return fake.init_rc;
}

int hid_exit(void)
{
	mark('Z'); fake.exit_calls++;
	return fake.exit_rc;
}

void hid_darwin_set_open_exclusive(int exclusive)
{
	mark('N');
	if (exclusive != 0) fake.calls_outside_contract++;
	if (!fake.setter_ignored) fake.exclusive = exclusive;
}

int hid_darwin_get_open_exclusive(void) { mark('G'); return fake.exclusive; }

int hid_darwin_is_device_open_exclusive(hid_device *handle)
{
	mark('X');
	if (handle != &device) fake.calls_outside_contract++;
	return fake.device_exclusive;
}

struct hid_device_info *hid_enumerate(unsigned short vid, unsigned short pid)
{
	mark('E'); fake.enumerate_calls++;
	fake.enumerated_vid = vid; fake.enumerated_pid = pid;
	return fake.enumeration;
}

void hid_free_enumeration(struct hid_device_info *entries)
{
	mark('F'); fake.free_calls++;
	if (entries != fake.enumeration) fake.calls_outside_contract++;
}

hid_device *hid_open_path(const char *path)
{
	mark('O'); fake.open_calls++;
	if (strcmp(path, "synthetic-path-A") != 0) fake.calls_outside_contract++;
	if (fake.stop_in_open) fake.stop = 1;
	return fake.open_fail ? NULL : &device;
}

int hid_get_report_descriptor(hid_device *handle, unsigned char *dst, size_t capacity)
{
	size_t count;
	mark('D'); fake.descriptor_calls++;
	if (handle != &device) fake.calls_outside_contract++;
	fake.descriptor_capacity = capacity;
	if (fake.io_in_descriptor) {
		unsigned char byte = 1, ch = 0;
		int read_rc = microlink_usb_get_char(&ch, 0);
		int write_rc = microlink_usb_send_bytes(&byte, 1);
		fake.io_rejected = read_rc < 0 && write_rc == 0;
	}
	if (fake.descriptor_error) return -1;
	count = fake.descriptor_length < capacity ? fake.descriptor_length : capacity;
	memcpy(dst, fake.descriptor, count);
	return (int)count;
}

int hid_read_timeout(hid_device *handle, unsigned char *dst, size_t capacity, int timeout)
{
	mark('R'); fake.read_calls++;
	if (handle != &device) fake.calls_outside_contract++;
	fake.read_capacity = capacity; fake.read_timeout = timeout;
	if (fake.read_result > 0 && (size_t)fake.read_result <= capacity) {
		memset(dst, 0x44, (size_t)fake.read_result);
		dst[0] = 7;
	}
	return fake.read_result;
}

int hid_write(hid_device *handle, const unsigned char *src, size_t length)
{
	mark('W'); fake.write_calls++;
	if (handle != &device) fake.calls_outside_contract++;
	fake.write_length = length;
	if (length <= sizeof(fake.written)) memcpy(fake.written, src, length);
	fake.now.tv_sec += fake.write_advance_seconds;
	return fake.write_result;
}

void hid_close(hid_device *handle)
{
	mark('C'); fake.close_calls++;
	if (handle != &device) fake.calls_outside_contract++;
}

int clock_gettime(clockid_t clock_id, struct timespec *now)
{
	fake.clock_calls++;
	if (clock_id != CLOCK_MONOTONIC) return -1;
	*now = fake.now;
	return fake.clock_rc;
}

static int stop_requested(void *user)
{
	fake_hidapi_t *host = user;
	host->stop_calls++;
	return host->stop;
}

static void reset_fake(unsigned int count)
{
	unsigned int i;
	memset(&fake, 0, sizeof(fake));
	fake.now.tv_sec = 1;
	fake.write_result = 64;
	memcpy(fake.descriptor, valid_descriptor, sizeof(valid_descriptor));
	fake.descriptor_length = sizeof(valid_descriptor);
	for (i = 0; i < count; i++) {
		struct hid_device_info *entry = &fake.entries[i];
		entry->path = i == 0 ? "synthetic-path-A" : "synthetic-path-B";
		entry->vendor_id = SYNTHETIC_VID;
		entry->product_id = SYNTHETIC_PID;
		entry->bus_type = HID_API_BUS_USB;
		entry->release_number = 0x0100;
		entry->interface_number = 0;
		entry->serial_number = L"synthetic-serial";
		entry->next = i + 1 < count ? &fake.entries[i + 1] : NULL;
	}
	fake.enumeration = count ? &fake.entries[0] : NULL;
}

static int create(mlink_hidapi_native_binding_t *binding)
{
	mlink_hidapi_native_config_t config = {
		SYNTHETIC_VID, SYNTHETIC_PID, stop_requested, &fake
	};
	return mlink_hidapi_native_create(&config, binding);
}

static int prepare(mlink_hidapi_native_binding_t *binding)
{
	unsigned int count = 0;
	return create(binding) == 0 && binding->ops->init(binding->user) == 0
		&& binding->ops->set_nonexclusive(binding->user) == 0
		&& binding->ops->select_unique(binding->user, &count) == 0 && count == 1;
}

static int finish(mlink_hidapi_native_binding_t *binding)
{
	CHECK(binding->ops->close(binding->user) == 0);
	CHECK(mlink_hidapi_native_dispose(binding) == 0);
	CHECK(binding->ops == NULL && binding->user == NULL);
	CHECK(fake.calls_outside_contract == 0);
	return 0;
}

static int diagnostic_is(mlink_hidapi_native_binding_t *binding,
	mlink_admission_stage_t stage, mlink_admission_reason_t reason,
	mlink_admission_parser_status_t parser_status)
{
	mlink_admission_diagnostic_t diagnostic;
	char order[sizeof(fake.order)];
	int calls = fake.exit_calls + fake.enumerate_calls + fake.free_calls + fake.open_calls
		+ fake.close_calls + fake.descriptor_calls + fake.read_calls + fake.write_calls;
	int stops = fake.stop_calls, clocks = fake.clock_calls;
	memcpy(order, fake.order, sizeof(order));
	diagnostic = binding->ops->get_admission_diagnostic(binding->user);
	if (diagnostic.stage != stage || diagnostic.reason != reason
	 || diagnostic.parser_status != parser_status) return 0;
	diagnostic = binding->ops->get_admission_diagnostic(binding->user);
	return diagnostic.stage == stage && diagnostic.reason == reason
		&& diagnostic.parser_status == parser_status
		&& calls == fake.exit_calls + fake.enumerate_calls + fake.free_calls + fake.open_calls
			+ fake.close_calls + fake.descriptor_calls + fake.read_calls + fake.write_calls
		&& stops == fake.stop_calls && clocks == fake.clock_calls
		&& memcmp(order, fake.order, sizeof(order)) == 0;
}

static int test_native_admission_diagnostics(void)
{
	mlink_hidapi_native_binding_t binding = {0};
	mlink_shared_layout_t layout;
	unsigned int selected_count = 0;
	mlink_admission_diagnostic_t diagnostic;
	reset_fake(0); fake.init_rc = -1;
	CHECK(create(&binding) == 0);
	diagnostic = binding.ops->get_admission_diagnostic(binding.user);
	CHECK(diagnostic.stage == MLINK_ADMISSION_STAGE_NONE
		&& diagnostic.reason == MLINK_ADMISSION_REASON_NONE
		&& diagnostic.parser_status == MLINK_ADMISSION_PARSER_NOT_RUN);
	CHECK(binding.ops->init(binding.user) != 0);
	CHECK(diagnostic_is(&binding, MLINK_ADMISSION_STAGE_INIT,
		MLINK_ADMISSION_REASON_HOST_FAILED, MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(finish(&binding) == 0);

	reset_fake(0); binding = (mlink_hidapi_native_binding_t){0};
	CHECK(create(&binding) == 0 && binding.ops->init(binding.user) == 0
		&& binding.ops->set_nonexclusive(binding.user) == 0);
	CHECK(binding.ops->select_unique(binding.user, &selected_count) != 0);
	CHECK(selected_count == 0 && fake.enumerate_calls == 1 && fake.free_calls == 1);
	CHECK(diagnostic_is(&binding, MLINK_ADMISSION_STAGE_SELECT,
		MLINK_ADMISSION_REASON_SELECTION_ZERO, MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(finish(&binding) == 0);

	reset_fake(2); binding = (mlink_hidapi_native_binding_t){0};
	CHECK(create(&binding) == 0 && binding.ops->init(binding.user) == 0
		&& binding.ops->set_nonexclusive(binding.user) == 0);
	CHECK(binding.ops->select_unique(binding.user, &selected_count) != 0);
	CHECK(selected_count == 2);
	CHECK(diagnostic_is(&binding, MLINK_ADMISSION_STAGE_SELECT,
		MLINK_ADMISSION_REASON_SELECTION_AMBIGUOUS, MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(finish(&binding) == 0);

	reset_fake(1); binding = (mlink_hidapi_native_binding_t){0};
	fake.entries[0].path = NULL;
	CHECK(create(&binding) == 0 && binding.ops->init(binding.user) == 0
		&& binding.ops->set_nonexclusive(binding.user) == 0);
	CHECK(binding.ops->select_unique(binding.user, &selected_count) != 0);
	CHECK(diagnostic_is(&binding, MLINK_ADMISSION_STAGE_SELECT,
		MLINK_ADMISSION_REASON_PATH_INVALID, MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(finish(&binding) == 0);

	reset_fake(2); binding = (mlink_hidapi_native_binding_t){0};
	fake.entries[1].path = "synthetic-path-A";
	fake.entries[1].release_number++;
	CHECK(create(&binding) == 0 && binding.ops->init(binding.user) == 0
		&& binding.ops->set_nonexclusive(binding.user) == 0);
	CHECK(binding.ops->select_unique(binding.user, &selected_count) != 0);
	CHECK(diagnostic_is(&binding, MLINK_ADMISSION_STAGE_SELECT,
		MLINK_ADMISSION_REASON_IDENTITY_INCONSISTENT, MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(finish(&binding) == 0);

	reset_fake(1025); binding = (mlink_hidapi_native_binding_t){0};
	for (size_t i = 1; i < 1025; i++) fake.entries[i].path = "synthetic-path-A";
	CHECK(create(&binding) == 0 && binding.ops->init(binding.user) == 0
		&& binding.ops->set_nonexclusive(binding.user) == 0);
	CHECK(binding.ops->select_unique(binding.user, &selected_count) != 0);
	CHECK(diagnostic_is(&binding, MLINK_ADMISSION_STAGE_SELECT,
		MLINK_ADMISSION_REASON_ENTRY_LIMIT, MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(finish(&binding) == 0);

	reset_fake(1); fake.open_fail = 1; binding = (mlink_hidapi_native_binding_t){0};
	CHECK(create(&binding) == 0 && binding.ops->init(binding.user) == 0
		&& binding.ops->set_nonexclusive(binding.user) == 0
		&& binding.ops->select_unique(binding.user, &selected_count) == 0);
	CHECK(binding.ops->open_selected(binding.user) != 0);
	CHECK(diagnostic_is(&binding, MLINK_ADMISSION_STAGE_OPEN,
		MLINK_ADMISSION_REASON_OPEN_NULL, MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(finish(&binding) == 0);

	reset_fake(1); fake.device_exclusive = 1; binding = (mlink_hidapi_native_binding_t){0};
	CHECK(prepare(&binding) && binding.ops->open_selected(binding.user) == 0);
	CHECK(binding.ops->read_layout(binding.user, &layout) != 0);
	CHECK(diagnostic_is(&binding, MLINK_ADMISSION_STAGE_LAYOUT,
		MLINK_ADMISSION_REASON_OPEN_EXCLUSIVE, MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(finish(&binding) == 0);

	reset_fake(1); fake.descriptor_error = 1; binding = (mlink_hidapi_native_binding_t){0};
	CHECK(prepare(&binding) && binding.ops->open_selected(binding.user) == 0);
	CHECK(binding.ops->read_layout(binding.user, &layout) != 0);
	CHECK(diagnostic_is(&binding, MLINK_ADMISSION_STAGE_LAYOUT,
		MLINK_ADMISSION_REASON_DESCRIPTOR_UNAVAILABLE, MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(finish(&binding) == 0);

	reset_fake(1); fake.descriptor_length = MLINK_HID_DESC_MAX_BYTES + 1;
	binding = (mlink_hidapi_native_binding_t){0};
	CHECK(prepare(&binding) && binding.ops->open_selected(binding.user) == 0);
	CHECK(binding.ops->read_layout(binding.user, &layout) != 0);
	CHECK(diagnostic_is(&binding, MLINK_ADMISSION_STAGE_LAYOUT,
		MLINK_ADMISSION_REASON_DESCRIPTOR_LIMIT, MLINK_ADMISSION_PARSER_NOT_RUN));
	CHECK(finish(&binding) == 0);

	reset_fake(1); binding = (mlink_hidapi_native_binding_t){0};
	fake.descriptor[14] = 0x3e;
	CHECK(prepare(&binding) && binding.ops->open_selected(binding.user) == 0);
	CHECK(binding.ops->read_layout(binding.user, &layout) != 0);
	CHECK(diagnostic_is(&binding, MLINK_ADMISSION_STAGE_LAYOUT,
		MLINK_ADMISSION_REASON_PARSER_REJECTED, MLINK_ADMISSION_PARSER_UNSUPPORTED));
	CHECK(finish(&binding) == 0);
	return 0;
}

static int test_factory_and_lifecycle(void)
{
	mlink_hidapi_native_binding_t binding = {0}, second = {0};
	mlink_hidapi_native_config_t invalid = {0, SYNTHETIC_PID, stop_requested, &fake};
	reset_fake(1);
	CHECK(mlink_hidapi_native_create(&invalid, &binding) != 0);
	invalid.vendor_id = SYNTHETIC_VID; invalid.stop_requested = NULL;
	CHECK(mlink_hidapi_native_create(&invalid, &binding) != 0);
	CHECK(create(&binding) == 0 && fake.order_len == 0);
	CHECK(create(&second) != 0);
	CHECK(mlink_hidapi_native_dispose(&binding) == 0 && fake.order_len == 0);
	CHECK(create(&binding) == 0);
	CHECK(binding.ops->set_nonexclusive(binding.user) != 0 && fake.order_len == 0);
	CHECK(binding.ops->init(binding.user) == 0);
	CHECK(binding.ops->init(binding.user) != 0 && strcmp(fake.order, "I") == 0);
	fake.exit_rc = -1;
	CHECK(mlink_hidapi_native_dispose(&binding) != 0 && binding.user != NULL);
	CHECK(create(&second) != 0);
	fake.exit_rc = 0;
	CHECK(mlink_hidapi_native_dispose(&binding) == 0 && fake.exit_calls == 2);
	return 0;
}

static int test_init_and_exclusive_failure(void)
{
	mlink_hidapi_native_binding_t binding = {0};
	reset_fake(1); fake.init_rc = -1;
	CHECK(create(&binding) == 0);
	CHECK(binding.ops->init(binding.user) != 0);
	CHECK(binding.ops->set_nonexclusive(binding.user) != 0);
	CHECK(finish(&binding) == 0 && strcmp(fake.order, "I") == 0);
	reset_fake(1); fake.setter_ignored = 1;
	CHECK(create(&binding) == 0 && binding.ops->init(binding.user) == 0);
	CHECK(binding.ops->set_nonexclusive(binding.user) != 0);
	CHECK(binding.ops->open_selected(binding.user) != 0);
	CHECK(finish(&binding) == 0 && strcmp(fake.order, "INGZ") == 0);
	return 0;
}

static int test_unique_paths(void)
{
	mlink_hidapi_native_binding_t binding = {0};
	unsigned int count;
	for (unsigned int entries = 0; entries <= 2; entries++) {
		reset_fake(entries);
		CHECK(create(&binding) == 0 && binding.ops->init(binding.user) == 0);
		CHECK(binding.ops->set_nonexclusive(binding.user) == 0);
		int rc = binding.ops->select_unique(binding.user, &count);
		CHECK(count == entries && (rc == 0) == (entries == 1));
		CHECK(fake.free_calls == 1 && fake.enumerate_calls == 1 && fake.open_calls == 0);
		CHECK(fake.enumerated_vid == SYNTHETIC_VID && fake.enumerated_pid == SYNTHETIC_PID);
		CHECK(binding.ops->select_unique(binding.user, &count) != 0 && fake.enumerate_calls == 1);
		CHECK(finish(&binding) == 0);
	}
	reset_fake(2); fake.entries[1].path = "synthetic-path-A";
	fake.entries[1].usage_page = 0xff86; fake.entries[1].usage = 1;
	CHECK(prepare(&binding) && fake.free_calls == 1);
	CHECK(finish(&binding) == 0);
	for (int conflict = 0; conflict < 4; conflict++) {
		reset_fake(2); fake.entries[1].path = "synthetic-path-A";
		if (conflict == 0) fake.entries[1].serial_number = L"different-synthetic-serial";
		if (conflict == 1) fake.entries[1].release_number++;
		if (conflict == 2) fake.entries[0].bus_type = HID_API_BUS_BLUETOOTH;
		if (conflict == 3) fake.entries[0].product_id++;
		CHECK(create(&binding) == 0 && binding.ops->init(binding.user) == 0);
		CHECK(binding.ops->set_nonexclusive(binding.user) == 0);
		CHECK(binding.ops->select_unique(binding.user, &count) != 0 && count == 0);
		CHECK(fake.free_calls == 1 && fake.open_calls == 0);
		CHECK(finish(&binding) == 0);
	}
	reset_fake(1); fake.entries[0].path = "";
	CHECK(create(&binding) == 0 && binding.ops->init(binding.user) == 0);
	CHECK(binding.ops->set_nonexclusive(binding.user) == 0);
	CHECK(binding.ops->select_unique(binding.user, &count) != 0 && count == 0);
	CHECK(fake.free_calls == 1 && finish(&binding) == 0);
	return 0;
}

static int test_open_and_owned_handle(void)
{
	mlink_hidapi_native_binding_t binding = {0};
	mlink_shared_layout_t layout;
	unsigned char bytes[65] = {0};
	reset_fake(1); fake.open_fail = 1;
	CHECK(prepare(&binding));
	CHECK(binding.ops->open_selected(binding.user) != 0 && fake.open_calls == 1);
	CHECK(binding.ops->open_selected(binding.user) != 0 && fake.open_calls == 1);
	CHECK(finish(&binding) == 0 && fake.close_calls == 0);
	reset_fake(1); CHECK(prepare(&binding));
	CHECK(binding.ops->open_selected(binding.user) == 0);
	CHECK(mlink_hidapi_native_dispose(&binding) != 0);
	CHECK(fake.close_calls == 0 && fake.exit_calls == 0);
	CHECK(binding.ops->read_report(binding.user, bytes, sizeof(bytes), 0) < 0);
	CHECK(binding.ops->write_report(binding.user, bytes, 64) < 0);
	CHECK(fake.read_calls == 0 && fake.write_calls == 0);
	CHECK(binding.ops->read_layout(binding.user, &layout) == 0);
	CHECK(strcmp(fake.order, "INGEFOXD") == 0);
	CHECK(layout.input_report_id == 7 && layout.output_report_id == 8);
	CHECK(layout.input_direction == MLINK_SHARED_INPUT && layout.output_direction == MLINK_SHARED_OUTPUT);
	CHECK(layout.input_report_length == 64 && layout.output_report_length == 64);
	CHECK(binding.ops->read_layout(binding.user, &layout) != 0);
	CHECK(fake.descriptor_calls == 1 && fake.descriptor_capacity == MLINK_HID_DESC_MAX_BYTES + 1U);
	CHECK(binding.ops->close(binding.user) == 0 && fake.close_calls == 1);
	CHECK(finish(&binding) == 0 && fake.close_calls == 1 && fake.exit_calls == 1);
	return 0;
}

static int test_layout_rejections_and_clipping(void)
{
	mlink_hidapi_native_binding_t binding = {0};
	mlink_shared_layout_t layout;
	for (int failure = 0; failure < 4; failure++) {
		reset_fake(1);
		if (failure == 0) fake.device_exclusive = 1;
		if (failure == 1) fake.device_exclusive = -1;
		if (failure == 2) fake.descriptor_error = 1;
		if (failure == 3) fake.descriptor_length--;
		CHECK(prepare(&binding) && binding.ops->open_selected(binding.user) == 0);
		memset(&layout, 0xff, sizeof(layout));
		CHECK(binding.ops->read_layout(binding.user, &layout) != 0);
		CHECK(layout.input_report_id == 0 && layout.output_report_length == 0);
		CHECK(fake.read_calls == 0 && fake.write_calls == 0);
		CHECK(fake.descriptor_calls == (failure < 2 ? 0 : 1));
		CHECK(mlink_hidapi_native_dispose(&binding) != 0);
		CHECK(finish(&binding) == 0 && fake.close_calls == 1);
	}
	for (int clipped = 0; clipped <= 1; clipped++) {
		mlink_hid_desc_result_t parsed;
		reset_fake(1);
		for (size_t i = sizeof(valid_descriptor); i < MLINK_HID_DESC_MAX_BYTES; i += 2) {
			fake.descriptor[i] = 0x05; fake.descriptor[i + 1] = 0x01;
		}
		CHECK(mlink_hid_desc_parse_checked(fake.descriptor, MLINK_HID_DESC_MAX_BYTES, &parsed) == MLINK_HID_DESC_OK);
		fake.descriptor_length = MLINK_HID_DESC_MAX_BYTES + (clipped ? 2U : 0U);
		fake.descriptor[MLINK_HID_DESC_MAX_BYTES] = 0x76;
		CHECK(prepare(&binding) && binding.ops->open_selected(binding.user) == 0);
		CHECK((binding.ops->read_layout(binding.user, &layout) == 0) == !clipped);
		CHECK(fake.descriptor_capacity == MLINK_HID_DESC_MAX_BYTES + 1U);
		CHECK(finish(&binding) == 0 && fake.close_calls == 1);
	}
	return 0;
}

static int test_forwarding_and_errors(void)
{
	mlink_hidapi_native_binding_t binding = {0};
	mlink_shared_layout_t layout;
	unsigned char data[65] = {8, 0x55};
	reset_fake(1); CHECK(prepare(&binding));
	CHECK(binding.ops->open_selected(binding.user) == 0);
	CHECK(binding.ops->read_layout(binding.user, &layout) == 0);
	fake.read_result = 3;
	CHECK(binding.ops->read_report(binding.user, data, sizeof(data), UINT_MAX) == 3);
	CHECK(fake.read_capacity == sizeof(data) && fake.read_timeout == INT_MAX);
	CHECK(binding.ops->read_report(binding.user, data, SIZE_MAX, 0) == 3);
	CHECK(fake.read_capacity == INT_MAX);
	fake.read_result = -1;
	CHECK(binding.ops->read_report(binding.user, data, sizeof(data), 4) < 0);
	fake.read_result = 66;
	CHECK(binding.ops->read_report(binding.user, data, sizeof(data), 4) < 0);
	for (int i = 0; i < 3; i++) {
		int results[] = {64, 63, -1};
		fake.write_result = results[i];
		CHECK(binding.ops->write_report(binding.user, data, 64) == results[i]);
		CHECK(fake.write_calls == i + 1 && fake.write_length == 64);
		CHECK(memcmp(fake.written, data, 64) == 0);
	}
	CHECK(binding.ops->write_report(binding.user, data, SIZE_MAX) < 0 && fake.write_calls == 3);
	fake.stop = 1;
	CHECK(binding.ops->read_report(binding.user, data, sizeof(data), 0) < 0 && fake.read_calls == 4);
	CHECK(binding.ops->write_report(binding.user, data, 64) < 0 && fake.write_calls == 3);
	CHECK(finish(&binding) == 0);
	return 0;
}

static int test_clock_and_stop(void)
{
	mlink_hidapi_native_binding_t binding = {0};
	int64_t now = -1;
	reset_fake(1); CHECK(create(&binding) == 0);
	fake.now.tv_nsec = 123456789;
	CHECK(binding.ops->monotonic_ms(binding.user, &now) == 0 && now == 1123);
	fake.now.tv_sec = INT64_MAX / 1000;
	fake.now.tv_nsec = 808000000;
	CHECK(binding.ops->monotonic_ms(binding.user, &now) < 0);
	fake.now.tv_nsec = 807000000;
	CHECK(binding.ops->monotonic_ms(binding.user, &now) == 0 && now == INT64_MAX);
	fake.now.tv_sec++;
	CHECK(binding.ops->monotonic_ms(binding.user, &now) < 0);
	fake.now.tv_sec = -1;
	CHECK(binding.ops->monotonic_ms(binding.user, &now) < 0);
	fake.now.tv_sec = 0; fake.now.tv_nsec = 1000000000;
	CHECK(binding.ops->monotonic_ms(binding.user, &now) < 0);
	fake.now.tv_nsec = 0; fake.clock_rc = -1;
	CHECK(binding.ops->monotonic_ms(binding.user, &now) < 0);
	fake.stop = 1;
	CHECK(binding.ops->stop_requested(binding.user) == 1);
	CHECK(binding.ops->init(binding.user) != 0 && fake.order_len == 0);
	CHECK(finish(&binding) == 0);
	return 0;
}

static int test_combined_core_native_parser(void)
{
	mlink_hidapi_native_binding_t binding = {0};
	unsigned char payload = 0x5a;
	for (int scenario = 0; scenario < 4; scenario++) {
		reset_fake(1);
		if (scenario == 1) fake.descriptor_length--;
		if (scenario == 2) fake.stop_in_open = 1;
		if (scenario == 3) fake.io_in_descriptor = 1;
		CHECK(create(&binding) == 0);
		CHECK(mlink_shared_test_bind(binding.ops, binding.user));
		CHECK(microlink_usb_guard_begin(10));
		CHECK((microlink_usb_open() != 0) == (scenario == 0));
		CHECK(fake.write_calls == 0 && fake.read_calls == 0);
		if (scenario == 0) {
			CHECK(strcmp(fake.order, "INGEFOXD") == 0);
			CHECK(microlink_usb_send_bytes(&payload, 1));
			CHECK(fake.write_calls == 1 && fake.write_length == 64);
			CHECK(fake.written[0] == 8 && fake.written[1] == 0x5a);
			for (size_t i = 2; i < 64; i++) CHECK(fake.written[i] == 0);
		} else {
			CHECK(fake.close_calls == 1);
			CHECK(!microlink_usb_send_bytes(&payload, 1) && fake.write_calls == 0);
			if (scenario == 2) CHECK(fake.descriptor_calls == 0);
			if (scenario == 3) CHECK(fake.io_rejected);
		}
		microlink_usb_close();
		mlink_shared_test_unbind();
		CHECK(finish(&binding) == 0 && fake.close_calls == 1);
	}
	return 0;
}

#ifdef MLINK_HIDAPI_OPERATIONAL_V2
static int test_operational_stop_cleanup_through_native_adapter(void)
{
	mlink_hidapi_native_binding_t binding = {0};
	mlink_health_snapshot_t health;
	unsigned char ordinary = 0x55;
	int cleanup_rc;
	reset_fake(1);
	CHECK(create(&binding) == 0);
	CHECK(mlink_shared_test_bind(binding.ops, binding.user));
	CHECK(mlink_shared_operational_begin());
	CHECK(microlink_usb_open());
	fake.stop = 1;
	mlink_shared_operational_stop();
	CHECK(!microlink_usb_send_bytes(&ordinary, 1));
	CHECK(fake.write_calls == 0);
	/* RED on the staged baseline: the authentic adapter currently rejects
	 * this sole guard-authorized F7 because its sticky Stop callback is true. */
	cleanup_rc = microlink_usb_cleanup_stop();
	if (!cleanup_rc) {
		fprintf(stderr, "FAIL operational cleanup after sticky Stop: cleanup_rc=0 hid_write_calls=%d\n",
			fake.write_calls);
		return 1;
	}
	CHECK(fake.write_calls == 1 && fake.write_length == 64);
	CHECK(fake.written[0] == 8 && fake.written[1] == 0xF7);
	for (size_t i = 2; i < 64; i++) CHECK(fake.written[i] == 0);
	health = mlink_shared_operational_snapshot();
	CHECK(health.reason == MLINK_HEALTH_STOP && !health.cleanup_failed);
	microlink_usb_close();
	CHECK(fake.close_calls == 1);
	CHECK(mlink_shared_operational_cleanup_complete());
	mlink_shared_test_unbind();
	CHECK(finish(&binding) == 0);
	CHECK(fake.close_calls == 1 && fake.exit_calls == 1);
	return 0;
}

enum test_write_mutation {
	TEST_WRITE_UNCHANGED = 0,
	TEST_WRITE_BAD_ID,
	TEST_WRITE_BAD_OPCODE,
	TEST_WRITE_BAD_PADDING,
	TEST_WRITE_SHORT_FRAME,
	TEST_WRITE_LONG_FRAME,
	TEST_WRITE_DUPLICATE
};

static mlink_shared_host_ops_t wrapped_ops;
static const mlink_shared_host_ops_t *wrapped_real_ops;
static enum test_write_mutation wrapped_mutation;
static int wrapped_probe_wrong_user;
static int wrapped_wrong_user_authorized;
static int wrapped_probe_null_user;
static int wrapped_null_user_authorized;
static ssize_t wrapped_duplicate_result;

static ssize_t wrapped_write_report(void *user, const unsigned char *src, size_t length)
{
	unsigned char frame[65] = {0};
	size_t frame_length = length <= sizeof(frame) ? length : sizeof(frame);
	ssize_t first;
	if (frame_length != 0) memcpy(frame, src, frame_length);
	if (wrapped_probe_wrong_user) {
		wrapped_wrong_user_authorized = mlink_shared_cleanup_stop_write_authorized(
			(void *)((char *)user + 1));
	}
	if (wrapped_probe_null_user) {
		wrapped_null_user_authorized = mlink_shared_cleanup_stop_write_authorized(NULL);
	}
	switch (wrapped_mutation) {
	case TEST_WRITE_BAD_ID: frame[0] ^= 1U; break;
	case TEST_WRITE_BAD_OPCODE: frame[1] = 0; break;
	case TEST_WRITE_BAD_PADDING: frame[2] = 1; break;
	case TEST_WRITE_SHORT_FRAME: frame_length = 63; break;
	case TEST_WRITE_LONG_FRAME: frame_length = 65; break;
	case TEST_WRITE_UNCHANGED:
	case TEST_WRITE_DUPLICATE:
	default: break;
	}
	first = wrapped_real_ops->write_report(user, frame, frame_length);
	if (wrapped_mutation == TEST_WRITE_DUPLICATE) {
		wrapped_duplicate_result = wrapped_real_ops->write_report(user, frame, frame_length);
	}
	return first;
}

static int open_operational_binding(mlink_hidapi_native_binding_t *binding, int wrap_write)
{
	reset_fake(1);
	CHECK(create(binding) == 0);
	if (wrap_write) {
		wrapped_ops = *binding->ops;
		wrapped_real_ops = binding->ops;
		wrapped_mutation = TEST_WRITE_UNCHANGED;
		wrapped_probe_wrong_user = 0;
		wrapped_wrong_user_authorized = 1;
		wrapped_probe_null_user = 0;
		wrapped_null_user_authorized = 1;
		wrapped_duplicate_result = 0;
		wrapped_ops.write_report = wrapped_write_report;
		CHECK(mlink_shared_test_bind(&wrapped_ops, binding->user));
	} else {
		CHECK(mlink_shared_test_bind(binding->ops, binding->user));
	}
	CHECK(mlink_shared_operational_begin());
	CHECK(microlink_usb_open());
	return 0;
}

static int close_operational_binding(mlink_hidapi_native_binding_t *binding,
	int expect_cleanup_complete)
{
	microlink_usb_close();
	CHECK(fake.close_calls == 1);
	CHECK((mlink_shared_operational_cleanup_complete() != 0) == expect_cleanup_complete);
	mlink_shared_test_unbind();
	CHECK(finish(binding) == 0);
	return 0;
}

static int test_operational_cleanup_counterproofs(void)
{
	mlink_hidapi_native_binding_t binding = {0};
	unsigned char ordinary[64] = {8, 0x55};
	unsigned char stop_frame[64] = {8, 0xF7};
	mlink_health_snapshot_t health;
	int reads_before, writes_before;

	/* Sticky Stop still blocks ordinary reads/writes and direct F7 calls. */
	CHECK(open_operational_binding(&binding, 0) == 0);
	fake.stop = 1;
	mlink_shared_operational_stop();
	reads_before = fake.read_calls;
	writes_before = fake.write_calls;
	CHECK(binding.ops->read_report(binding.user, ordinary, sizeof(ordinary), 0) < 0);
	CHECK(binding.ops->write_report(binding.user, ordinary, sizeof(ordinary)) < 0);
	CHECK(binding.ops->write_report(binding.user, stop_frame, sizeof(stop_frame)) < 0);
	CHECK(fake.read_calls == reads_before && fake.write_calls == writes_before);
	CHECK(microlink_usb_cleanup_stop());
	CHECK(fake.write_calls == 1);
	CHECK(microlink_usb_cleanup_stop() == 0 && fake.write_calls == 1);
	CHECK(close_operational_binding(&binding, 1) == 0);

	/* Invalid ID, opcode, padding and report lengths cannot use the phase gate. */
	for (enum test_write_mutation mutation = TEST_WRITE_BAD_ID;
		mutation <= TEST_WRITE_LONG_FRAME; mutation++) {
		CHECK(open_operational_binding(&binding, 1) == 0);
		fake.stop = 1;
		mlink_shared_operational_stop();
		wrapped_mutation = mutation;
		CHECK(!microlink_usb_cleanup_stop());
		CHECK(fake.write_calls == 0);
		CHECK(close_operational_binding(&binding, 0) == 0);
	}

	/* The query is owner-bound, yet a false foreign-owner query does not
	 * interfere with the current owner's one valid cleanup report. */
	CHECK(open_operational_binding(&binding, 1) == 0);
	fake.stop = 1;
	mlink_shared_operational_stop();
	wrapped_probe_wrong_user = 1;
	wrapped_probe_null_user = 1;
	CHECK(microlink_usb_cleanup_stop());
	CHECK(!wrapped_wrong_user_authorized && !wrapped_null_user_authorized
		&& fake.write_calls == 1);
	CHECK(close_operational_binding(&binding, 1) == 0);

	/* A second adapter call while the guard capability is live is rejected
	 * after the first call consumes the native one-shot bit. */
	CHECK(open_operational_binding(&binding, 1) == 0);
	fake.stop = 1;
	mlink_shared_operational_stop();
	wrapped_mutation = TEST_WRITE_DUPLICATE;
	CHECK(microlink_usb_cleanup_stop());
	CHECK(fake.write_calls == 1 && wrapped_duplicate_result < 0);
	CHECK(close_operational_binding(&binding, 1) == 0);

	/* Short/error writes and a fake clock jump beyond the cleanup budget fail
	 * once; the guard does not retry. */
	for (int scenario = 0; scenario < 3; scenario++) {
		CHECK(open_operational_binding(&binding, 0) == 0);
		fake.stop = 1;
		mlink_shared_operational_stop();
		if (scenario == 0) fake.write_result = 63;
		if (scenario == 1) fake.write_result = -1;
		if (scenario == 2) fake.write_advance_seconds = 3;
		CHECK(!microlink_usb_cleanup_stop());
		CHECK(!microlink_usb_cleanup_stop());
		CHECK(fake.write_calls == 1);
		health = mlink_shared_operational_snapshot();
		CHECK(health.cleanup_failed);
		CHECK(close_operational_binding(&binding, 0) == 0);
	}

	/* With no Stop latch, the completed cleanup still consumes the adapter's
	 * one-shot bit and blocks direct F7 and ordinary writes before close. */
	CHECK(open_operational_binding(&binding, 1) == 0);
	mlink_shared_operational_fail();
	wrapped_probe_wrong_user = 1;
	wrapped_probe_null_user = 1;
	wrapped_mutation = TEST_WRITE_DUPLICATE;
	CHECK(fake.stop == 0);
	CHECK(microlink_usb_cleanup_stop());
	CHECK(!wrapped_wrong_user_authorized && !wrapped_null_user_authorized);
	CHECK(wrapped_duplicate_result < 0 && fake.write_calls == 1);
	CHECK(binding.ops->write_report(binding.user, stop_frame, sizeof(stop_frame)) < 0);
	CHECK(binding.ops->write_report(binding.user, ordinary, sizeof(ordinary)) < 0);
	CHECK(fake.write_calls == 1);
	CHECK(close_operational_binding(&binding, 1) == 0);
	return 0;
}
#endif

int main(void)
{
	int (*tests[])(void) = {
		test_factory_and_lifecycle, test_init_and_exclusive_failure,
		test_unique_paths, test_open_and_owned_handle,
		test_layout_rejections_and_clipping, test_forwarding_and_errors,
		test_clock_and_stop, test_combined_core_native_parser,
		test_native_admission_diagnostics
	};
#ifdef MLINK_HIDAPI_OPERATIONAL_V2
	int (*operational_tests[])(void) = {
		test_operational_stop_cleanup_through_native_adapter,
		test_operational_cleanup_counterproofs
	};
#endif
	for (size_t i = 0; i < sizeof(tests) / sizeof(tests[0]); i++) {
		if (tests[i]() != 0) return 1;
	}
#ifdef MLINK_HIDAPI_OPERATIONAL_V2
	for (size_t i = 0; i < sizeof(operational_tests) / sizeof(operational_tests[0]); i++) {
		if (operational_tests[i]() != 0) return 1;
	}
#endif
#ifdef MLINK_HIDAPI_OPERATIONAL_V2
	puts("PASS native HIDAPI binding fake cases=11 (including operational cleanup + checked parser)");
#else
	puts("PASS native HIDAPI binding fake cases=9 (including core + checked parser)");
#endif
	puts("Scope: synthetic HIDAPI symbols only; no device, HIDAPI library or OS HID calls");
	return 0;
}
#endif
