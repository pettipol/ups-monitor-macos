/* SPDX-License-Identifier: GPL-2.0-or-later
 * Synthetic offline tests for APC Microlink interrupt-OUT completion. */
#include <stdarg.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>

#if USB_WRITE_CANDIDATE != 0 && USB_WRITE_CANDIDATE != 1
#error "USB_WRITE_CANDIDATE must be 0 or 1"
#endif

#define MLINK_USB_REPORT_PAYLOAD_LEN 63U
#define MLINK_USB_REPORT_TOTAL_LEN (1U + MLINK_USB_REPORT_PAYLOAD_LEN)
#define MLINK_USB_WRITE_TIMEOUT_MS 1000U
#define USB_ENDPOINT_OUT 0x00
#define LIBUSB_ERROR_PIPE (-9)
#define LIBUSB_ERROR_NO_DEVICE (-4)
#define LIBUSB_ERROR_BUSY (-6)
#define LIBUSB_ERROR_TIMEOUT (-7)
#define LIBUSB_SUCCESS 0
#define PRIuSIZE "zu"

typedef struct { int marker; } usb_dev_handle;
typedef unsigned char *usb_ctrl_charbuf;
typedef struct { int hid_ep_out; } usb_subdriver_t;

static usb_dev_handle fake_device;
static usb_dev_handle *udev = &fake_device;
static usb_subdriver_t usb_subdriver = { .hid_ep_out = 2 };
static int mlink_report_out = 7;
static int usb_device_gone;
static int controlled_status;
static int controlled_actual_length;
static int transfer_calls;
static int fatal_calls;
static int last_endpoint;
static int last_size;
static int last_timeout;
static usb_dev_handle *last_device;
static unsigned char last_report[MLINK_USB_REPORT_TOTAL_LEN];
static char last_log[256];
static unsigned int failures;

static void check(int condition, const char *name)
{
	if (!condition) {
		printf("FAIL %s\n", name);
		failures++;
	}
}

static void upsdebugx(int level, const char *format, ...)
{
	va_list arguments;
	(void)level;
	va_start(arguments, format);
	vsnprintf(last_log, sizeof(last_log), format, arguments);
	va_end(arguments);
}

static const char *nut_usb_strerror(int error)
{
	(void)error;
	return "synthetic USB error";
}

static void microlink_usb_handle_busy(const char *context)
{
	(void)context;
}

static int libusb_interrupt_transfer(usb_dev_handle *device, unsigned char endpoint,
	unsigned char *bytes, int size, int *actual_length, unsigned int timeout)
{
	transfer_calls++;
	last_device = device;
	last_endpoint = (int)endpoint;
	last_size = size;
	last_timeout = (int)timeout;
	if (size >= 0 && size <= (int)sizeof(last_report)) {
		memcpy(last_report, bytes, (size_t)size);
	}
	*actual_length = controlled_actual_length;
	return controlled_status;
}

static void fatalx(int status, const char *format, ...)
{
	(void)status;
	(void)format;
	fatal_calls++;
}

#include "usb_write_completion_generated.c"

static void reset_fixture(void)
{
	memset(last_report, 0, sizeof(last_report));
	last_log[0] = '\0';
	transfer_calls = 0;
	fatal_calls = 0;
	last_endpoint = -1;
	last_size = -1;
	last_timeout = -1;
	last_device = NULL;
	controlled_status = LIBUSB_SUCCESS;
	controlled_actual_length = (int)MLINK_USB_REPORT_TOTAL_LEN;
	udev = &fake_device;
	mlink_report_out = 7;
	usb_device_gone = 0;
}

static int send_with_result(int status, int actual_length)
{
	static const unsigned char payload[] = { 0x12, 0x34, 0x56 };
	reset_fixture();
	controlled_status = status;
	controlled_actual_length = actual_length;
	return microlink_usb_send_bytes(payload, sizeof(payload));
}

static int is_zero_padded_report(void)
{
	static const unsigned char payload[] = { 0x12, 0x34, 0x56 };
	size_t i;
	if (last_report[0] != 7 || memcmp(last_report + 1, payload, sizeof(payload)) != 0) {
		return 0;
	}
	for (i = 1 + sizeof(payload); i < sizeof(last_report); i++) {
		if (last_report[i] != 0) {
			return 0;
		}
	}
	return 1;
}

int main(void)
{
	static const int short_results[] = { 0, 1, 63, 65 };
	static const char *short_names[] = {
		"zero-byte short write rejected",
		"one-byte short write rejected",
		"63-byte short write rejected",
		"unexpected oversized completion rejected"
	};
	static const unsigned char payload[] = { 0x12, 0x34, 0x56 };
	size_t i;
	int result;

	reset_fixture();
	check(microlink_usb_send_bytes(payload, sizeof(payload)) == 1,
		"64-byte completion succeeds");
	check(transfer_calls == 1 && last_device == &fake_device
		&& last_endpoint == 2 && last_size == 64 && last_timeout == 1000,
		"write uses expected device, endpoint, report size and timeout");
	check(fatal_calls == 0, "valid wrapper arguments do not call fatalx");
	check(is_zero_padded_report(), "write report ID, payload and zero padding are preserved");

	for (i = 0; i < sizeof(short_results) / sizeof(short_results[0]); i++) {
		result = send_with_result(LIBUSB_SUCCESS, short_results[i]);
		check(result == 0 && transfer_calls == 1
			&& strstr(last_log, "unexpected byte count") != NULL,
			short_names[i]);
	}

	check(send_with_result(LIBUSB_ERROR_TIMEOUT, 0) == 0 && transfer_calls == 1,
		"timeout with zero partial bytes fails without retry");
	check(send_with_result(LIBUSB_ERROR_TIMEOUT, 1) == 0 && transfer_calls == 1,
		"timeout with one partial byte fails without retry");
	check(send_with_result(LIBUSB_ERROR_TIMEOUT, 63) == 0 && transfer_calls == 1,
		"timeout with 63 partial bytes fails without retry");
	check(send_with_result(-2, 64) == 0 && transfer_calls == 1,
		"negative write error fails without retry");
	check(send_with_result(LIBUSB_ERROR_PIPE, 0) == 0 && transfer_calls == 1,
		"stalled endpoint fails without retry");
	check(send_with_result(LIBUSB_ERROR_BUSY, 0) == 0 && transfer_calls == 1,
		"busy endpoint fails without retry");
	reset_fixture();
	controlled_status = LIBUSB_ERROR_NO_DEVICE;
	controlled_actual_length = 0;
	check(microlink_usb_send_bytes(payload, sizeof(payload)) == 0
		&& usb_device_gone == 1 && transfer_calls == 1,
		"device removal remains reported without retry");

	reset_fixture();
	udev = NULL;
	check(microlink_usb_send_bytes(payload, sizeof(payload)) == 0 && transfer_calls == 0,
		"null device handle performs no write");
	reset_fixture();
	mlink_report_out = 0;
	check(microlink_usb_send_bytes(payload, sizeof(payload)) == 0 && transfer_calls == 0,
		"missing output report ID performs no write");
	reset_fixture();
	check(microlink_usb_send_bytes(payload, MLINK_USB_REPORT_PAYLOAD_LEN + 1U) == 0
		&& transfer_calls == 0, "oversized payload performs no write");

	if (failures != 0) {
		printf("%u validation check(s) failed\n", failures);
		return 1;
	}
	puts("all USB write completion checks passed");
	return 0;
}
