/* SPDX-License-Identifier: GPL-2.0-or-later
 * Checked, allocation-free HID report descriptor validation for Microlink.
 * Derived in part from NUT hidparser.c tokenizer/state behavior; see source
 * provenance below. This is not the legacy NUT parser ABI.
 */
#ifndef APCMICROLINK_HID_DESCRIPTOR_CHECKED_H
#define APCMICROLINK_HID_DESCRIPTOR_CHECKED_H

#include <stddef.h>
#include <stdint.h>

#define MLINK_HID_DESC_MAX_BYTES 6144U
#define MLINK_HID_DESC_MAX_COLLECTION_DEPTH 10U
#define MLINK_HID_DESC_MAX_MAINS 500U
#define MLINK_HID_DESC_MAX_LOCAL_USAGES 64U
#define MLINK_HID_DESC_MAX_REPORT_BITS 65536U

/* Provenance snapshot: NUT provenance9-20261012/results/usb-A/source/drivers/
 * hidparser.c SHA-256 8294a17df65c9ed35b5ba482eb1c543a6f321fe951965bb071851bbc01f22216
 * hidtypes.h SHA-256 4269271dae5b023b4bb6aec62c7b19edfa91b74dda7ad85cf755f7703100aedb
 * Material function origins: HIDParse(), ResetLocalState(), GetReportOffset().
 * This local provenance snapshot has no commit ID asserted.
 */

typedef enum mlink_hid_desc_status {
	MLINK_HID_DESC_OK = 0,
	MLINK_HID_DESC_MALFORMED,
	MLINK_HID_DESC_UNSUPPORTED,
	MLINK_HID_DESC_LIMIT,
	MLINK_HID_DESC_NO_TUNNEL,
	MLINK_HID_DESC_AMBIGUOUS
} mlink_hid_desc_status_t;

typedef enum mlink_hid_report_type {
	MLINK_HID_REPORT_INPUT = 1,
	MLINK_HID_REPORT_OUTPUT = 2,
	MLINK_HID_REPORT_FEATURE = 3
} mlink_hid_report_type_t;

typedef struct mlink_hid_main_record {
	uint32_t usage;
	uint32_t bit_offset;
	uint32_t bit_size;
	uint32_t count;
	uint32_t attributes;
	uint8_t report_id;
	uint8_t type;
} mlink_hid_main_record_t;

typedef struct mlink_hid_desc_result {
	mlink_hid_desc_status_t status;
	size_t error_offset;
	size_t main_count;
	mlink_hid_main_record_t mains[MLINK_HID_DESC_MAX_MAINS];
	uint32_t total_bits[256][3]; /* Input, Output, Feature; includes padding. */
	uint8_t input_report_id;
	uint8_t output_report_id;
	uint32_t input_report_length;
	uint32_t output_report_length;
} mlink_hid_desc_result_t;

mlink_hid_desc_status_t mlink_hid_desc_parse_checked(
	const uint8_t *bytes, size_t length, mlink_hid_desc_result_t *result);

#endif
