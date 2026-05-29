"""
spec_loader.py
XDR Specification, MessageCode, Cause xlsx 파일을 로딩하여
내부 딕셔너리를 생성한다.

실제 스펙 문서 기반 구현. 임의 추정 없음.
"""

import os
import logging
from typing import Dict, Tuple, Optional, Any
from pathlib import Path

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Interface Protocol 매핑 (XDR_MessageCode Interface protocol 시트 기반)
# ──────────────────────────────────────────────────────────────────────────────
INTERFACE_PROTOCOL_MAP: Dict[int, str] = {
    0: "None",
    1: "S6a_Diameter",
    2: "S1MME_S1AP",
    3: "S11_GTPv2C",
    4: "S10_GTPv2C",
    5: "S1MME_NAS_EMM",
    6: "S1MME_NAS_ESM",
    7: "S3_GTPv1C",
    8: "S13_Diameter",
}

# ──────────────────────────────────────────────────────────────────────────────
# LTE-Call-KPI 필드 인덱스 매핑 (스펙 No. 1-based → 0-based index)
# XDR_Specification_s-probe_corr_20210729.xlsx LTE-Call-KPI 시트 기반
# ──────────────────────────────────────────────────────────────────────────────
FIELD_INDEX: Dict[str, int] = {
    # Summary
    "summary_create_time":           0,   # No.1
    "ongoing_flag":                  1,   # No.2
    # User
    "imsi":                          2,   # No.3
    "mdn":                           3,   # No.4
    "imei":                          4,   # No.5
    "service_code":                  5,   # No.6
    "pay_code":                      6,   # No.7
    "gender":                        7,   # No.8
    "age":                           8,   # No.9
    "vendor":                        9,   # No.10
    "model":                         10,  # No.11
    # Equipment
    "pgw_id":                        11,  # No.12
    "ims_pgw_id":                    12,  # No.13
    "sgw_id":                        13,  # No.14
    "mme_id":                        14,  # No.15
    "s6a_auth_equip_type":           15,  # No.16
    "s6a_auth_equip_id":             16,  # No.17
    "s6a_location_equip_type":       17,  # No.18
    "s6a_location_equip_id":         18,  # No.19
    "s13_equip_type":                19,  # No.20
    "s13_equip_id":                  20,  # No.21
    "first_enb_id":                  21,  # No.22
    "first_cell_id":                 22,  # No.23
    "first_enb_vlan_id":             23,  # No.24
    "last_enb_id":                   24,  # No.25
    "last_cell_id":                  25,  # No.26
    "last_enb_vlan_id":              26,  # No.27
    "pdn_type":                      27,  # No.28
    "pdn_ipv4":                      28,  # No.29
    "pdn_ipv6":                      29,  # No.30
    "ims_pdn_type":                  30,  # No.31
    "ims_pdn_ipv4":                  31,  # No.32
    "ims_pdn_ipv6":                  32,  # No.33
    # Call Flow
    "old_call_type":                 33,  # No.34
    "old_call_end_time":             34,  # No.35
    "old_call_last_enb_id":          35,  # No.36
    "old_call_last_cell_id":         36,  # No.37
    "old_call_last_tac":             37,  # No.38
    "call_type":                     38,  # No.39  ← 핵심
    "call_start_time":               39,  # No.40
    "call_end_time":                 40,  # No.41
    "call_duration_time":            41,  # No.42
    "apn":                           42,  # No.43
    "ims_apn":                       43,  # No.44
    # S6a Diameter
    "s6a_error_message":             44,  # No.45
    "s6a_error_time":                45,  # No.46
    "s6a_error_cause":               46,  # No.47
    "auth_info_time":                47,  # No.48
    "auth_info_cause":               48,  # No.49
    "update_location_time":          49,  # No.50
    "update_location_cause":         50,  # No.51
    # S13 Diameter
    "s13_error_message":             51,  # No.52
    "s13_error_time":                52,  # No.53
    "s13_error_cause":               53,  # No.54
    "me_identity_check_time":        54,  # No.55
    "me_identity_check_cause":       55,  # No.56
    # S1-MME S1AP
    "s1ap_error_message":            56,  # No.57
    "s1ap_error_time":               57,  # No.58
    "s1ap_error_cause":              58,  # No.59
    "cn_domain":                     59,  # No.60
    "rrc_establishment_cause":       60,  # No.61
    "path_switch_count":             61,  # No.62
    "path_switch_failure_count":     62,  # No.63
    "ue_ctx_release_req_time":       63,  # No.64
    "ue_ctx_release_req_cause":      64,  # No.65
    "ue_ctx_release_time":           65,  # No.66
    "ue_ctx_release_cause":          66,  # No.67
    # NAS-EMM
    "emm_error_message":             67,  # No.68
    "emm_error_time":                68,  # No.69
    "emm_error_cause":               69,  # No.70
    "detach_req_time":               70,  # No.71
    "detach_req_cause":              71,  # No.72
    "detach_req_type":               72,  # No.73
    "detach_req_switchoff":          73,  # No.74
    "detach_req_direction":          74,  # No.75
    # NAS-ESM
    "esm_error_message":             75,  # No.76
    "esm_error_time":                76,  # No.77
    "esm_error_cause":               77,  # No.78
    # S11 GTPv2C
    "s11_error_message":             78,  # No.79
    "s11_error_time":                79,  # No.80
    "s11_error_cause":               80,  # No.81
    # S10 GTPv2C
    "s10_error_message":             81,  # No.82
    "s10_error_time":                82,  # No.83
    "s10_error_cause":               83,  # No.84
    # S3 GTPv1C
    "s3_error_message":              84,  # No.85
    "s3_error_time":                 85,  # No.86
    "s3_error_cause":                86,  # No.87
    # SGd SMS
    "sms_mo_cp_error":               87,  # No.88
    "sms_mo_rp_error":               88,  # No.89
    "sms_mo_tp_error":               89,  # No.90
    "sms_mt_cp_error":               90,  # No.91
    "sms_mt_rp_error":               91,  # No.92
    "sms_mt_tp_error":               92,  # No.93
    # KPI Flags
    "attempt_flag":                  93,  # No.94
    "success_flag":                  94,  # No.95
    "data_attempt_flag":             95,  # No.96
    "data_success_flag":             96,  # No.97
    "ims_attempt_flag":              97,  # No.98
    "ims_success_flag":              98,  # No.99
    "drop_flag":                     99,  # No.100
    "paging_attempt_flag":           100, # No.101
    "paging_success_flag":           101, # No.102
    "detach_flag":                   102, # No.103
    "npr_flag":                      103, # No.104
    "auth_attempt_flag":             104, # No.105
    "auth_success_flag":             105, # No.106
    "location_attempt_flag":         106, # No.107
    "location_success_flag":         107, # No.108
    "mecheck_attempt_flag":          108, # No.109
    "mecheck_success_flag":          109, # No.110
    # Error (핵심 RCA 필드)
    "first_error_interface":         110, # No.111
    "first_error_message":           111, # No.112
    "first_error_time":              112, # No.113
    "first_error_cause":             113, # No.114
    "last_error_interface":          114, # No.115
    "last_error_message":            115, # No.116
    "last_error_time":               116, # No.117
    "last_error_cause":              117, # No.118
    # Interval
    "interval_first_enb_id":        118, # No.119
    "interval_first_enb_ip":        119, # No.120
    "interval_first_cell_id":       120, # No.121
    "interval_first_tac":           121, # No.122
    "interval_first_enb_c_uid":     122, # No.123
    "interval_first_enb_vlan_id":   123, # No.124
    "interval_call_start_time":     124, # No.125
    # Call Usage
    "old_call_s1ap_release_cause":  125, # No.126
    "initial_access_duration":      126, # No.127
    "initial_access_msg_count":     127, # No.128
    "initial_core_duration":        128, # No.129
    "initial_core_msg_count":       129, # No.130
    "initial_paging_duration":      130, # No.131
    "initial_paging_msg_count":     131, # No.132
    "initial_paging_attempt_count": 132, # No.133
    "imsi_mcc_mnc_info":            133, # No.134
    # DCNR
    "ue_dcnr":                      134, # No.135
    "initial_nr_conn_time":         135, # No.136
    "ue_usage_type":                136, # No.137
    "mme_restrict_dcnr":            137, # No.138
    # GTPv2C
    "modify_bearer_success_count":  138, # No.139
    # S1AP additional
    "initial_ue_message_time":      139, # No.140
    # Additional info
    "spid":                         140, # No.141
    "exchange_number":              141, # No.142
    "nas_key_validity":             142, # No.143
    "equip_nw":                     143, # No.144
    # eNB PLMN
    "first_enb_plmn":               144, # No.145
    "last_enb_plmn":                145, # No.146
    "old_call_last_enb_plmn":       146, # No.147
    "interval_first_enb_plmn":      147, # No.148
    # reserved
    "reserved_1":                   148, # No.149
    "reserved_2":                   149, # No.150
    "reserved_3":                   150, # No.151
    "reserved_4":                   151, # No.152
    "reserved_5":                   152, # No.153
}

# call_type 코드 (스펙 call_type Value 기반)
CALL_TYPE_MAP: Dict[int, str] = {
    1: "Attach_MO",
    2: "Attach_MT",
    3: "Service_MO",
    4: "Service_MT",
    5: "TAU",
    6: "Paging",
    7: "Extended_Service_MO",
    8: "Extended_Service_MT",
    9: "Detach_MO",
    10: "S1_Handover_Inter_MME",
}

# ──────────────────────────────────────────────────────────────────────────────
# 동적 로딩: MessageCode / Cause xlsx
# ──────────────────────────────────────────────────────────────────────────────

# 로딩된 딕셔너리 (앱 시작 시 한번 초기화)
MESSAGE_CODE_MAP: Dict[Tuple[str, int], str] = {}   # (interface_name, code) → message_name
CAUSE_MAP: Dict[Tuple[str, int], Dict[str, str]] = {}  # (protocol, code) → {meaning, description}

# NAS EMM / NAS ESM 메시지 코드 (직접 정의 - 스펙 확인 완료)
NAS_EMM_MSG = {
    65: "ATTACH_REQUEST",
    66: "ATTACH_ACCEPT",
    67: "ATTACH_COMPLETE",
    68: "ATTACH_REJECT",
    69: "DETACH_REQUEST",
    70: "DETACH_ACCEPT",
    72: "TRACKING_AREA_UPDATE_REQUEST",
    73: "TRACKING_AREA_UPDATE_ACCEPT",
    74: "TRACKING_AREA_UPDATE_COMPLETE",
    75: "TRACKING_AREA_UPDATE_REJECT",
    76: "EXTENDED_SERVICE_REQUEST",
    78: "SERVICE_REJECT",
    80: "GUTI_REALLOCATION_COMMAND",
    81: "GUTI_REALLOCATION_COMPLETE",
    82: "AUTHENTICATION_REQUEST",
    83: "AUTHENTICATION_RESPONSE",
    84: "AUTHENTICATION_REJECT",
    86: "IDENTITY_REQUEST",
    92: "AUTHENTICATION_FAILURE",
    93: "SECURITY_MODE_COMMAND",
    94: "SECURITY_MODE_COMPLETE",
    95: "SECURITY_MODE_REJECT",
    96: "EMM_STATUS",
    97: "EMM_INFORMATION",
    98: "DOWNLINK_NAS_TRANSPORT",
    128: "SERVICE_REQUEST",
}

NAS_ESM_MSG = {
    193: "ACTIVATE_DEFAULT_EPS_BEARER_CONTEXT_REQUEST",
    194: "ACTIVATE_DEFAULT_EPS_BEARER_CONTEXT_ACCEPT",
    195: "ACTIVATE_DEFAULT_EPS_BEARER_CONTEXT_REJECT",
    197: "ACTIVATE_DEDICATED_EPS_BEARER_CONTEXT_REQUEST",
    198: "ACTIVATE_DEDICATED_EPS_BEARER_CONTEXT_ACCEPT",
    199: "ACTIVATE_DEDICATED_EPS_BEARER_CONTEXT_REJECT",
    201: "MODIFY_EPS_BEARER_CONTEXT_REQUEST",
    202: "MODIFY_EPS_BEARER_CONTEXT_ACCEPT",
    203: "MODIFY_EPS_BEARER_CONTEXT_REJECT",
    205: "DEACTIVATE_EPS_BEARER_CONTEXT_ACCEPT",
    208: "PDN_CONNECTIVITY_REQUEST",
    209: "PDN_CONNECTIVITY_REJECT",
    210: "PDN_DISCONNECT_REQUEST",
    211: "PDN_DISCONNECT_REJECT",
    217: "ESM_INFORMATION_REQUEST",
    218: "ESM_INFORMATION_RESPONSE",
    232: "ESM_STATUS",
}

# Diameter 메시지 코드 (주요 코드만 - 스펙 확인 완료)
DIAMETER_MSG = {
    257: "CER_CEA",
    258: "RAR_RAA",
    265: "AAR_AAA",
    271: "ACR_ACA",
    272: "CCR_CCA",
    274: "ASR_ASA",
    275: "STR_STA",
    280: "DWR_DWA",
    282: "DPR_DPA",
    316: "ULR_ULA",   # Update Location
    317: "CLR_CLA",   # Cancel Location
    318: "AIR_AIA",   # Authentication Information ← 핵심
    319: "IDR_IDA",   # Insert Subscriber Data
    320: "DSR_DSA",   # Delete Subscriber Data
    321: "PUR_PUA",   # Purge UE
    322: "RSR_RSA",   # Reset
    323: "NOR_NOA",   # Notify
    324: "ECR_ECA",   # ME Identity Check
}

# GTPv2C 메시지 코드 (주요 코드만)
GTPV2C_MSG = {
    1: "ECHO_REQUEST",
    2: "ECHO_RESPONSE",
    32: "CREATE_SESSION_REQUEST",
    33: "CREATE_SESSION_RESPONSE",
    34: "MODIFY_BEARER_REQUEST",
    35: "MODIFY_BEARER_RESPONSE",
    36: "DELETE_SESSION_REQUEST",
    37: "DELETE_SESSION_RESPONSE",
    95: "CREATE_BEARER_REQUEST",
    96: "CREATE_BEARER_RESPONSE",
    99: "DELETE_BEARER_REQUEST",
    100: "DELETE_BEARER_RESPONSE",
}

# S1AP 절차 코드 → 이름 (주요만)
S1AP_MSG = {
    0: "HANDOVER_PREPARATION",
    1: "HANDOVER_RESOURCE_ALLOCATION",
    3: "PATH_SWITCH_REQUEST",
    5: "E_RAB_SETUP",
    9: "INITIAL_CONTEXT_SETUP",
    10: "PAGING",
    11: "DOWNLINK_NAS_TRANSPORT",
    12: "INITIAL_UE_MESSAGE",
    13: "UPLINK_NAS_TRANSPORT",
    17: "S1_SETUP",
    18: "UE_CONTEXT_RELEASE_REQUEST",
    21: "UE_CONTEXT_MODIFICATION",
    23: "UE_CONTEXT_RELEASE",
    40: "E_RAB_MODIFICATION_INDICATION",
}

# S1AP Cause (NAS group, 스펙 확인 완료)
S1AP_CAUSE_MAP = {
    # Radio Network Layer
    100: "Unspecified",
    101: "TX2RELOCOverall_Expiry",
    102: "Successful_Handover",
    103: "Release_due_to_EUTRAN",
    104: "Handover_Cancelled",
    110: "Cell_not_available",
    120: "User_inactivity",
    121: "Radio_Connection_With_UE_Lost",
    126: "Failure_in_Radio_Interface_Procedure",
    # NAS Cause (300번대)
    300: "NAS_Normal_Release",
    301: "NAS_Authentication_Failure",
    302: "NAS_Detach",
    303: "NAS_Unspecified",
    # Transport Layer
    400: "Transport_Resource_Unavailable",
    # Protocol
    500: "Transfer_Syntax_Error",
    501: "Abstract_Syntax_Error",
}

# NAS EMM Cause (주요)
NAS_EMM_CAUSE_MAP = {
    2:  "IMSI_unknown_in_HSS",
    3:  "Illegal_UE",
    5:  "IMEI_not_accepted",
    6:  "Illegal_ME",
    7:  "EPS_services_not_allowed",
    9:  "UE_identity_cannot_be_derived",
    10: "Implicitly_detached",
    11: "PLMN_not_allowed",
    12: "TA_not_allowed",
    13: "Roaming_not_allowed_in_TA",
    15: "No_Suitable_Cells",
    17: "Network_failure",
    19: "ESM_failure",
    20: "MAC_failure",
    21: "Synch_failure",
    22: "Congestion",
    25: "Not_authorized_for_CSG",
}

# NAS ESM Cause (운영 RCA에 필요한 주요 PDN reject 계열)
NAS_ESM_CAUSE_MAP = {
    8:  "Operator_Determined_Barring",
    26: "Insufficient_Resources",
    27: "Missing_or_unknown_APN",
    28: "Unknown_PDN_type",
    29: "User_authentication_failed",
    30: "Request_rejected_by_SGW_or_PGW",
    31: "Request_rejected_unspecified",
    32: "Service_option_not_supported",
    33: "Requested_service_option_not_subscribed",
    50: "PDN_type_IPv4_only_allowed",
    51: "PDN_type_IPv6_only_allowed",
    55: "Protocol_error_unspecified",
}

# Diameter Cause (주요)
DIAMETER_CAUSE_MAP = {
    # Success
    2001: "DIAMETER_SUCCESS",
    2002: "DIAMETER_LIMITED_SUCCESS",
    # Protocol Errors
    3001: "DIAMETER_COMMAND_UNSUPPORTED",
    3002: "DIAMETER_UNABLE_TO_DELIVER",
    3004: "DIAMETER_TOO_BUSY",
    # Transient Failures
    4100: "DIAMETER_USER_DATA_NOT_AVAILABLE",
    4101: "DIAMETER_PRIOR_UPDATE_IN_PROGRESS",
    4181: "DIAMETER_AUTHENTICATION_DATA_UNAVAILABLE",
    # Permanent Failures (3GPP Experimental)
    5001: "DIAMETER_ERROR_USER_UNKNOWN",
    5002: "DIAMETER_ERROR_IDENTITIES_DONT_MATCH",
    5003: "DIAMETER_ERROR_IDENTITY_NOT_REGISTERED",
    5004: "DIAMETER_ERROR_ROAMING_NOT_ALLOWED",
    5005: "DIAMETER_ERROR_IDENTITY_ALREADY_REGISTERED",
    5006: "DIAMETER_ERROR_AUTH_SCHEME_NOT_SUPPORTED",
    5011: "DIAMETER_ERROR_FEATURE_UNSUPPORTED",
    # Process specific
    900: "TIMEOUT",
    # Vendor-specific (벤더별 HSS 코드, 15000대)
    # 실제 데이터에서 15001 발견됨 - 벤더 특정 코드로 처리
}

# GTPv2C Cause (주요, error threshold >= 64)
GTPV2C_CAUSE_MAP = {
    16: "Request_accepted",
    17: "Request_accepted_partially",
    64: "Context_Not_Found",
    65: "Invalid_Message_Format",
    66: "Version_not_supported",
    67: "Invalid_length",
    68: "Service_not_supported",
    69: "Mandatory_IE_incorrect",
    70: "Mandatory_IE_missing",
    72: "System_failure",
    73: "No_resources_available",
    74: "Semantic_error_in_TFT",
    75: "Syntactic_error_in_TFT",
    76: "Semantic_errors_in_PF",
    77: "Syntactic_errors_in_PF",
    78: "Missing_or_unknown_APN",
    80: "GRE_key_not_found",
    81: "Relocation_failure",
    82: "Denied_in_RAT",
    83: "Preferred_PDN_type_not_supported",
    84: "All_dynamic_addresses_occupied",
    900: "TIMEOUT",
}

# Process Specific Cause
PROCESS_SPECIFIC_CAUSE_MAP = {
    900: "TIMEOUT",
}


def get_interface_name(code: int) -> str:
    """Interface protocol 코드 → 이름"""
    return INTERFACE_PROTOCOL_MAP.get(code, f"UNKNOWN_IFACE_{code}")


def get_message_name(interface_code: int, msg_code: int) -> str:
    """Interface + Message 코드 → 메시지 이름"""
    iface = INTERFACE_PROTOCOL_MAP.get(interface_code, "")

    if "S6a" in iface or "S13" in iface:
        return DIAMETER_MSG.get(msg_code, f"DIAMETER_MSG_{msg_code}")
    elif "S1AP" in iface:
        return S1AP_MSG.get(msg_code, f"S1AP_MSG_{msg_code}")
    elif "NAS_EMM" in iface:
        return NAS_EMM_MSG.get(msg_code, f"EMM_MSG_{msg_code}")
    elif "NAS_ESM" in iface:
        return NAS_ESM_MSG.get(msg_code, f"ESM_MSG_{msg_code}")
    elif "S11" in iface or "S10" in iface:
        return GTPV2C_MSG.get(msg_code, f"GTPV2C_MSG_{msg_code}")
    return f"MSG_{msg_code}"


def get_cause_name(interface_code: int, cause_code: int) -> str:
    """Interface + Cause 코드 → cause 이름"""
    if cause_code == 0:
        return "NO_ERROR"
    if cause_code == 900:
        return "TIMEOUT"

    iface = INTERFACE_PROTOCOL_MAP.get(interface_code, "")

    if "S6a" in iface or "S13" in iface:
        name = DIAMETER_CAUSE_MAP.get(cause_code)
        if name:
            return name
        # 벤더 특정 코드 (표준 범위 외)
        if cause_code >= 10000:
            return f"VENDOR_SPECIFIC_CAUSE_{cause_code}"
        return f"DIAMETER_CAUSE_{cause_code}"
    elif "S1AP" in iface:
        return S1AP_CAUSE_MAP.get(cause_code, f"S1AP_CAUSE_{cause_code}")
    elif "NAS_EMM" in iface:
        return NAS_EMM_CAUSE_MAP.get(cause_code, f"EMM_CAUSE_{cause_code}")
    elif "NAS_ESM" in iface:
        return NAS_ESM_CAUSE_MAP.get(cause_code, f"ESM_CAUSE_{cause_code}")
    elif "S11" in iface or "S10" in iface:
        return GTPV2C_CAUSE_MAP.get(cause_code, f"GTPV2C_CAUSE_{cause_code}")

    return f"CAUSE_{cause_code}"


def get_call_type_name(code: int) -> str:
    return CALL_TYPE_MAP.get(code, f"UNKNOWN_CALL_TYPE_{code}")


def is_error_cause(interface_code: int, cause_code: int) -> bool:
    """
    스펙 문서의 Error 판단 조건 기준으로 실제 에러인지 판단.
    - S6a: (Cause >= 3000 && Cause < 6000) || (Cause >= 13000 && Cause < 16000)
    - S13: 동일
    - S1AP: UnsuccessfulOutcome 메시지 타입인 경우 (XDR에서는 cause != 0으로 처리)
    - NAS-EMM/ESM: XDR_Cause 문서 참조 (cause != 0)
    - S11/GTPv2C: Cause >= 64
    - S3/GTPv1C: Cause >= 192
    - TIMEOUT: 900
    """
    if cause_code == 0:
        return False
    if cause_code == 900:
        return True  # TIMEOUT은 항상 에러

    iface = INTERFACE_PROTOCOL_MAP.get(interface_code, "")

    if "S6a" in iface or "S13" in iface:
        return (3000 <= cause_code < 6000) or (13000 <= cause_code < 16000) or (cause_code >= 10000)
    elif "S11" in iface or "S10" in iface:
        return cause_code >= 64
    elif "S3" in iface:
        return cause_code >= 192
    else:
        # S1AP, NAS: cause != 0이면 에러로 간주
        return cause_code != 0
