#!/usr/bin/env python3
"""
Takes a firmware image (dumped from any SX567 variant - AutoSet, VAuto, CS PaceWave)
and patches the CCX region so all EDF file types contain the full universal signal set.

This helper uses the shared ASFirmware framework from lib/as10_firmware.py for
firmware layout, globals[], UART name resolution, and CRC finalization.
"""

import struct
import sys
from pathlib import Path

from lib.as10_firmware import ASFirmware


ADDR_BASE = 0x08000000
CCX_OFFSET = 0x4000
CCX_SIZE = 0x3C000
CCX_BASE = ADDR_BASE + CCX_OFFSET
CCX_CRC_OFFSET = 0x3C000 - 2


FULL_FLASH_SIZE = 0x100000  # 1MB


# BRP.edf signals: [EDF label, UART var, samples_per_60s_record]
BRP_SIGNALS = [
    ("Flow.40ms",       "RFL", 1500),  # 25 Hz
    ("Press.40ms",      "MKP", 1500),
    ("TrigCycEvt.40ms", "TCV", 1500),
    ("Crc16",           "DCR", 1),
]

# PLD.edf signals
PLD_SIGNALS = [
    ("MaskPress.2s", "MKF", 30),   # 0.5 Hz
    ("Press.2s",     "MKI", 30),
    ("EprPress.2s",  "MKE", 30),
    ("Leak.2s",      "LKF", 30),
    ("RespRate.2s",  "RRR", 30),
    ("TidVol.2s",    "TDD", 30),
    ("MinVent.2s",   "MV5", 30),
    ("TgtVent.2s",   "TGT", 30),
    ("IERatio.2s",   "IER", 30),
    ("Snore.2s",     "SNI", 30),
    ("FlowLim.2s",   "FFL", 30),
    ("B5ITime.2s",   "IN5", 30),
    ("B5ETime.2s",   "EX5", 30),
    ("Ti.2s",        "INT", 30),
    ("Crc16",        "DCR", 1),
]

# SAD.edf signals (same across all variants)
SAD_SIGNALS = [
    ("Pulse.1s", "HRT", 60),  # 1 Hz
    ("SpO2.1s",  "SAO", 60),
    ("Crc16",    "DCR", 1),
]

# STR.edf signal names - must be in EXACT field record order.
# strtab[i] labels field_record[i].
STR_SIGNAL_NAMES = [
    # [0] Date
    "Date",
    # [1-3] CSL_EMPTY - always at these positions in all 4 variants
    "MaskOn", "MaskOff", "MaskEvents",
    # [4-11] Shared base - identical across all 4 variants
    "Duration", "OnDuration", "PatientHours", "Mode",
    "S.RampEnable", "S.RampTime", "S.C.StartPress", "S.C.Press",
    # [12-15] VA/CP/AS shared (not in AV)
    "S.EPR.ClinEnable", "S.EPR.EPREnable", "S.EPR.Level", "S.EPR.EPRType",
    # [16-29] VA-only (14 entries)
    "S.BL.StartPress", "S.BL.IPAP", "S.BL.EPAP", "S.EasyBreathe",
    "S.VA.StartPress", "S.VA.MaxIPAP", "S.VA.MinEPAP", "S.VA.PS",
    "S.RiseEnable", "S.RiseTime", "S.Cycle", "S.Trigger",
    "S.TiMax", "S.TiMin",
    # [30-33] AS-only (4 entries)
    "S.AS.Comfort", "S.AS.StartPress", "S.AS.MaxPress", "S.AS.MinPress",
    # [34-42] AV-only (9 entries)
    "S.AV.StartPress", "S.AV.EPAP", "S.AV.MaxPS", "S.AV.MinPS",
    "S.AA.StartPress", "S.AA.MaxEPAP", "S.AA.MinEPAP", "S.AA.MaxPS", "S.AA.MinPS",
    # [43-56] Union shared tail (14 entries)
    "S.SmartStart", "S.PtAccess", "S.ABFilter", "S.LeakAlert",
    "S.Mask", "S.Tube", "S.ClimateControl", "S.HumEnable",
    "S.HumLevel", "S.TempEnable", "S.Temp", "S.ExternalHum",
    "HeatedTube", "Humidifier",
    # [57-69] EVE block 1 - identical across all 4 variants (13 entries)
    "BlowPress.95", "BlowPress.5", "Flow.95", "Flow.5",
    "BlowFlow.50", "AmbHumidity.50", "HumTemp.50", "HTubeTemp.50",
    "HTubePow.50", "HumPow.50", "SpO2.50", "SpO2.95", "SpO2.Max",
    # [70] CSL_B
    "SpO2Thresh",
    # [71] CSL_C (AS-only)
    "CSR",
    # [72] EXT (VA/CP only)
    "SpontCyc%",
    # [73-103] EVE block 2 - union (31 entries: base 22 + VA 6 + AV 3)
    "MaskPress.50", "MaskPress.95", "MaskPress.Max",
    "TgtIPAP.50", "TgtIPAP.95", "TgtIPAP.Max",
    "TgtEPAP.50", "TgtEPAP.95", "TgtEPAP.Max",
    "Leak.50", "Leak.95", "Leak.70", "Leak.Max",
    "MinVent.50", "MinVent.95", "MinVent.Max",
    "RespRate.50", "RespRate.95", "RespRate.Max",
    "TidVol.50", "TidVol.95", "TidVol.Max",
    "IERatio.50", "IERatio.95", "IERatio.Max",
    "Ti.50", "Ti.95", "Ti.Max",
    "TgtVent.50", "TgtVent.95", "TgtVent.Max",
    # [104-109] AEV (6 entries - superset, AV has 3-subset)
    "AHI", "HI", "AI", "OAI", "CAI", "UAI",
    # [110] AEV (AS-only, 81-field AutoSet variants)
    "RIN",
    # [111-115] CSL tail - identical across all 4 variants
    "Fault.Device", "Fault.Alarm", "Fault.Humidifier", "Fault.HeatedTube", "Crc16",
]

assert len(STR_SIGNAL_NAMES) == 116

# g[12] field records - interleaved superset
#
# Pattern observed across all 4 variants:
#   CSL_A block -> EVE1(13) -> CSL_B -> [CSL_C] -> [EXT] -> EVE2 -> AEV -> CSL_tail

# Record templates
_CSL_A = bytes([0x0D, 0x00, 0xFF, 0x7F, 0xFF, 0x7F, 0x00, 0x00, 0x00, 0x00])
_CSL_B = bytes([0x0D, 0x00, 0xFF, 0x7F, 0xFF, 0x7F, 0x00, 0x02, 0x01, 0x00])
_CSL_C = bytes([0x0D, 0x00, 0xFF, 0x7F, 0xFF, 0x7F, 0x00, 0x00, 0x01, 0x00])
_EMPTY = bytes([0x00, 0x00, 0xFF, 0x7F, 0xFF, 0x7F, 0x00, 0x00, 0x00, 0x00])

def _eve(var_name, percentile, gate):
    # Record bytes +6/+7 are a percentile and sampling gate (1=ZTE, 2=ZLE).
    return ('eve', var_name, percentile, gate)

def _aev(var_name):
    return ('aev', var_name)

def _ext(var_a, var_b):
    return ('ext', var_a, var_b)

_EXT_REC = _ext("TBB", "TBC")

# Complete interleaved field record sequence (116 records)
SUPERSET_RECORDS = [
    # [0] Date
    _CSL_A,
    # [1-3] EMPTY (MaskOn, MaskOff, MaskEvents)
    _EMPTY, _EMPTY, _EMPTY,
    # [4-56] CSL_A settings (53 entries)
    _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A,   # [4-11] shared base
    _CSL_A, _CSL_A, _CSL_A, _CSL_A,                                   # [12-15] VA/CP/AS
    _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A,   # [16-29] VA-only
    _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A,
    _CSL_A, _CSL_A, _CSL_A, _CSL_A,                                   # [30-33] AS-only
    _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A,   # [34-42] AV-only
    _CSL_A,
    _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A,   # [43-56] union tail
    _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A,
    # [57-69] EVE block 1 (13 entries)
    _eve("BPA", 95, 1), _eve("BPA", 5, 1),
    _eve("RFA", 95, 1), _eve("RFA", 5, 1),
    _eve("AFL", 50, 1), _eve("ABH", 50, 1),
    _eve("HPT", 50, 1), _eve("HTT", 50, 1),
    _eve("TPA", 50, 1), _eve("PPA", 50, 1),
    _eve("SAV", 50, 2), _eve("SAV", 95, 2), _eve("SAV", 100, 2),
    # [70] CSL_B (SpO2Thresh)
    _CSL_B,
    # [71] CSL_C (CSR - AS-only)
    _CSL_C,
    # [72] EXT (SpontCyc%)
    _EXT_REC,
    # [73-103] EVE block 2 (31 entries - base 22 + VA 6 + AV 3)
    _eve("MAP", 50, 1), _eve("MAP", 95, 1), _eve("MAP", 100, 1),
    _eve("AIP", 50, 2), _eve("AIP", 95, 2), _eve("AIP", 100, 2),
    _eve("AEP", 50, 2), _eve("AEP", 95, 2), _eve("AEP", 100, 2),
    _eve("LKP", 50, 2), _eve("LKP", 95, 2), _eve("LKP", 70, 2), _eve("LKP", 100, 2),
    _eve("MVT", 50, 2), _eve("MVT", 95, 2), _eve("MVT", 100, 2),
    _eve("RR1", 50, 2), _eve("RR1", 95, 2), _eve("RR1", 100, 2),
    _eve("ATI", 50, 2), _eve("ATI", 95, 2), _eve("ATI", 100, 2),
    # IERatio, Ti
    _eve("AIE", 50, 2), _eve("AIE", 95, 2), _eve("AIE", 100, 2),
    _eve("MIS", 50, 2), _eve("MIS", 95, 2), _eve("MIS", 100, 2),
    # TgtVent
    _eve("MTT", 50, 2), _eve("MTT", 95, 2), _eve("MTT", 100, 2),
    # [104-109] AEV (6 entries)
    _aev("AHC"), _aev("HYC"), _aev("AIC"),
    _aev("CAC"), _aev("OAC"), _aev("UAC"),
    # [110] AEV (RIN - AS-only)
    _aev("RDC"),
    # [111-115] CSL tail (Fault.*, Crc16)
    _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A,
]

SUPERSET_FIELD_COUNT = len(SUPERSET_RECORDS)
assert SUPERSET_FIELD_COUNT == 116

# g[13]+0x10 -> col1 start, g[13]+0x14 -> col2 start.
# col1 = EDF signal column ID for this record
# col2 = sample count (1 for normal, 10 for MaskOn/MaskOff)
SUPERSET_COL1 = [
    # [0] Date
    "LSD",
    # [1-3] EMPTY (MaskOn, MaskOff, MaskEvents)
    "ONT", "OFT", "MSE",
    # [4-11] Shared base
    "OND", "THD", "PHM", "MOP", "RMA", "RMT", "STP", "IPC",
    # [12-15] VA/CP/AS shared (not in AV)
    "EPA", "EPX", "EPR", "EPT",
    # [16-29] VA-only (14 entries)
    "EPS", "IPP", "EPP", "EBE", "STV", "MXI", "MNE", "SPT",
    "RSC", "RST", "VCS", "VTS", "ITX", "ITN",
    # [30-33] AS-only (4 entries)
    "AFC", "STU", "MPA", "MPI",
    # [34-42] AV-only (9 entries)
    "STE", "EEP", "MXS", "MNS", "EAS", "EAX", "EAI", "AXS", "ANS",
    # [43-56] Union shared tail (14 entries)
    "SST", "ACC", "ABF", "ALR", "MSK", "TBT", "CCO", "HMX",
    "HMS", "HTX", "HTS", "HME", "HTB", "HUM",
    # [57-69] EVE block 1 (13)
    "BP9", "BP5", "RF9", "RF5", "BFM", "ABM", "HHM", "HTM",
    "TPM", "HPM", "SOM", "SO9", "SOX",
    # [70] CSL_B, [71] CSL_C
    "SAU", "CSD",
    # [72] EXT
    "VCR",
    # [73-103] EVE block 2 (31)
    "MSP", "PM9", "PMA", "PIM", "PI9", "PIA", "PEM", "PE9", "PEA",
    "LKM", "LK9", "LK7", "LMX", "VTM", "VT9", "VTA",
    "RRM", "RR9", "RRA", "TVM", "TV9", "TVA",
    "IEM", "IE9", "IEA", "ISM", "IS9", "ISA",
    "VAM", "VA9", "VAA",
    # [104-109] AEV (6)
    "AHI", "HIS", "AIS", "CLI", "OPI", "UAI",
    # [110] AEV (RIN)
    "RIN",
    # [111-115] CSL tail (5)
    "SYS", "SYT", "SYC", "SYH", "DCR",
]
SUPERSET_COL2 = [
    # [0] Date
    0x0001,
    # [1-3] EMPTY (MaskOn=10, MaskOff=10, MaskEvents=1)
    0x000A, 0x000A, 0x0001,
    # [4-56] CSL_A settings: all 1
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    # [57-69] EVE1: all 1
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    # [70] CSL_B, [71] CSL_C, [72] EXT
    0x0001, 0x0001, 0x0001,
    # [73-103] EVE2: all 1
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001,
    # [104-109] AEV: all 1
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    # [110] AEV (RIN)
    0x0001,
    # [111-115] CSL tail: all 1
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
]
assert len(SUPERSET_COL1) == SUPERSET_FIELD_COUNT
assert len(SUPERSET_COL2) == SUPERSET_FIELD_COUNT

G12_HEADER_SIZE = 72  # 3 x 24B headers (CSL, AEV, EVE)

# g[12] header gap arrays - var_id arrays pointed to by CSL/AEV/EVE headers at +0x10.
# These sit between g[11]+96 and g[12] in native firmware, contiguous: CSL[n] + AEV[m] + EVE[k].
# The count field at header +0x08 specifies how many u16 entries per type.
G12_GAP_CSL = ["ETI", "CSZ", "CSR", "DCR"]  # superset (4)
G12_GAP_AEV = ["ETI", "DCR"]                # all variants (2)
G12_GAP_EVE = ["ETI", "DUR", "AET", "DCR"]  # all variants (4)

# g[13] var_id slots that are masked to 0x0000 in some variants.
# The NPD array at g[13]+0x24 lists var_ids, count at g[13]+0x44.
# AS/AV have count=7, VA/CP have count=8 ; slot [7] is AIE (IERatio).
PSTR_VARID_MASKS = {
    0x32: "AIE",  # NPD[7]: IERatio - AS/AV=0x0000, VA/CP=AIE
}
PSTR_NPD_COUNT_OFF = 0x44
PSTR_NPD_SUPERSET_COUNT = 8

# g[21] history-summary rules, stored after the g[20] PDL header (16 bytes each).
# Reduce source fields from EEPROM SESSION/STR history into destination variables.
# AS=13, VA/CP=20, AV=17 records. Superset=21.
# Var IDs drift across firmware versions, so resolve record endpoints by UART name.
G20_SUPERSET_RECORD_SPECS = [
    ("WRD", "OND", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ZAI", "PI9", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ZAE", "PE9", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("LRS", "LK9", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ZAT", "TVM", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ZAR", "RRM", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ZAM", "VTM", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ZAZ", "ISM", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ZA1", "IEM", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ZA2", "VAM", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ZAY", "VCR", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ARD", "AHI", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("TRD", "AIS", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("CRD", "OPI", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("VRD", "OND", 0x00000100, 0xFFFFFFFF, 0x000000F0),
    ("DRD", "OND", 0x00000100, 0xFFFFFFFF, 0xFFFFFFFF),
    ("XRD", "OND", 0x00000200, 0xFFFFFFFF, 0xFFFFFFFF),
    ("AQD", "AHI", 0x00000300, 0xFFFFFFFF, 0xFFFFFFFF),
    ("MQD", "LK7", 0x00000300, 0xFFFFFFFF, 0xFFFFFFFF),
    ("UQD", "OND", 0x00000300, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ZRH", "SYC", 0x00000300, 0xFFFFFFFF, 0xFFFFFFFF),
]
G20_SUPERSET_COUNT = len(G20_SUPERSET_RECORD_SPECS)
G20_HEADER_SIZE = 12  # "PDL\0" + ptr(4) + 0x0022 + 0x0000

# g[26] tail superset, var_id pool referenced by g[27] APN/CSN/BRH records
# g[26] = 8 records x 20B at 0x080093F4, followed by a packed var_id pool.
# g[27] APN/CSN/BRH records point INTO this pool with overlapping windows.
#
# APN: [AET, DUR]               same all variants, cnt=2
# CSN: [CET, CSR]               AS has both (cnt=2), VA/AV only CSR (cnt=1)
# BRH: [TID, ATP, INT, EXT]     VA has 4 (cnt=4), AS/AV only first 2 (cnt=2)
G26_TAIL_APN = ["AET", "DUR"]
G26_TAIL_CSN = ["CET", "CSR"]
G26_TAIL_BRH = ["TID", "ATP", "INT", "EXT"]

# g[26] record data array superset.
#
# Each g[26] record (20B) has ptr1 -> var_id array, ptr2 -> rate array.
# These arrays sit in a packed region BEFORE the g[26] records and are NOT
# part of the g[26] 160B copy. Bumping a record's count without relocating
# its ptr1/ptr2 arrays causes the firmware to read into adjacent array data.
#
# Fix: for every record whose count changes, write the full superset array
# into the merge block and redirect ptr1/ptr2.
#
# TCE (record[0]): AS/ASV=3, VA=4. VA prepends TrigCycEvt (TCV).
# PBT (record[1]): AS/VA=5, ASV=6. ASV inserts TgtVent (TGT) at [1].
# Records 2-7 (PMD/FTX/RAW/DRT/CPU/SSK): identical across all variants.
G26_DATA_PATCHES = {
    # record_index: (superset_varids, superset_rates)
    0: (["TCV", "MKP", "RFL", "LYK"],                # TCE: VA order
        [0x0001, 0x0001, 0x0001, 0x0001]),
    1: (["MV5", "TGT", "RRR", "LKF", "TIP", "TEP"],  # PBT: ASV order
        [0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001]),
}

# g[27] record count superset
# Record layout: 3 x 16B records (APN, CSN, BRH) + 24B shared tail (OXH var_ids+rates)
# Counts:        APN: max(2,2,2)=2   CSN: max(2,1,1)=2   BRH: max(2,4,2)=4
G27_APN_SUPERSET_COUNT = 2
G27_CSN_SUPERSET_COUNT = 2  # AS=2, VA/AV=1
G27_BRH_SUPERSET_COUNT = 4  # VA=4, AS/AV=2

# g[14] NPD count, byte at g[14]+16 inside the NPD sub-record header.
# AS/AV=7, VA=8. Parallels g[13]+0x44 NPD count (already patched).
G14_NPD_SUPERSET_COUNT = 8


# g[4] variable descriptor activation flags.
G4_ACT_PATCHES = [
    "MPA", "IPP", "MTT", "TGT", "ATP", "VA9", "VAA", "VAM", "RIN", "CLI", "OPI",
    "UAI", "EPR", "IE9", "IEA", "IEM", "IER", "AIE", "IN5", "EX5", "INT",
    "EXT", "ISM", "IS9", "ISA", "MIS", "VCR", "CSD", "CSZ", "CET", "ZAI", "ZAE",
    "ZAT", "ZA1", "ZAM", "ZAR", "ZAZ", "ZA2", "ZAY", "CRD", "CSG", "CSC",
    "CSE", "CST", "CSS", "AGT", "PSP", "CAC", "OAC", "RCR", "SBD", "TBB",
    "TBC", "TCT", "DGT", "IGT", "EGT", "QXI", "RDC", "VGT", "XGT", "ZAV",
    "MPI", "STU", "MNE", "MXI", "SPT", "STV", "EPP", "EPS", "RST", "ITN",
    "ITX", "EEP", "MNS", "MXS", "STE", "EAX", "EAI", "ANS", "AXS", "EAS",
]

# g[8] variable descriptor activation flags.
# Records where at least one variant has ACT=1 but not all do.
G8_ACT_PATCHES = [
    "EBE", "RSC", "AFC", "ALR", "HME", "EPA", "EPX", "EPT",
    "TCV", "VCS", "VTS", "CSR", "CYI", "TRI", "ZLM",
]



class CCXMergeError(Exception):
    pass


class CCXImage(bytearray):
    def u16(self, off):
        return struct.unpack_from('<H', self, off)[0]

    def u32(self, off):
        return struct.unpack_from('<I', self, off)[0]

    def write_u8(self, off, val):
        self[off] = val & 0xFF

    def write_u16(self, off, val):
        struct.pack_into('<H', self, off, val)

    def write_u32(self, off, val):
        struct.pack_into('<I', self, off, val)


def ccx_off(addr):
    """Convert absolute flash address to CCX file offset."""
    if not (CCX_BASE <= addr < CCX_BASE + CCX_SIZE):
        raise CCXMergeError(f"Address 0x{addr:08X} outside CCX range")
    return addr - CCX_BASE


def ccx_addr(off):
    return CCX_BASE + off


def resolve_signal_specs(signal_specs, var_id):
    return [(label, var_id(name), samples) for label, name, samples in signal_specs]


def build_field_record(rec, var_id):
    if isinstance(rec, bytes):
        return rec

    kind = rec[0]
    if kind == 'eve':
        return bytes([0x0D, 0x02]) + struct.pack(
            '<HHBBH', var_id(rec[1]), 0x7FFF, rec[2], rec[3], 0x0001)
    if kind == 'aev':
        return bytes([0x0D, 0x01]) + struct.pack(
            '<HHHH', var_id(rec[1]), 0x7FFF, 0x0000, 0x0002)
    if kind == 'ext':
        # Keep the native ratio record's parameter bytes, not a resolved var_id.
        return bytes([0x0D, 0x03]) + struct.pack(
            '<HHBBH', var_id(rec[1]), var_id(rec[2]), 0, 2, 0x0001)

    raise CCXMergeError(f"Unknown g[12] field record spec {rec!r}")


def infer_table_id_base(name_lookup, count, required_ids=(), expected_base=None):
    ids = set(name_lookup.values())
    required_ids = list(required_ids)

    def candidate_matches(candidate):
        end = candidate + count
        if not all(candidate + i in ids for i in range(count)):
            return False
        return all(candidate <= vid < end for vid in required_ids)

    if expected_base is not None and candidate_matches(expected_base):
        return expected_base

    matches = [candidate for candidate in sorted(ids) if candidate_matches(candidate)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise CCXMergeError(
            f"Descriptor table id base is ambiguous for {count} records: "
            + ", ".join(f"0x{m:04X}" for m in matches[:8]))

    raise CCXMergeError(f"Cannot infer descriptor table id base for {count} records")


def descriptor_record_offsets(data, g, name_lookup, table_idx, stride, names, expected_base=None):
    next_idx = table_idx + 1
    table_start = ccx_off(g[table_idx])
    table_end = ccx_off(g[next_idx])
    if table_end <= table_start or (table_end - table_start) % stride:
        raise CCXMergeError(f"globals[{table_idx}] table size is not aligned")

    count = (table_end - table_start) // stride
    vids = {}
    for name in names:
        vid = name_lookup.get(name.upper())
        if vid is None:
            raise CCXMergeError(f"Cannot resolve UART var name {name!r}")
        vids[name] = vid

    base = infer_table_id_base(name_lookup, count, vids.values(), expected_base)
    offsets = {}
    for name, vid in vids.items():
        rec_idx = vid - base
        if rec_idx < 0 or rec_idx >= count:
            raise CCXMergeError(
                f"{name} var_id 0x{vid:04X} is outside globals[{table_idx}] "
                f"range 0x{base:04X}..0x{base + count - 1:04X}")
        offsets[name] = table_start + rec_idx * stride

    return offsets


def split_u32_words(value):
    return value & 0xFFFF, (value >> 16) & 0xFFFF


def resolve_g20_records(var_id):
    records = []
    for dst, src, flags, param_a, param_b in G20_SUPERSET_RECORD_SPECS:
        flag_lo, flag_hi = split_u32_words(flags)
        pa_lo, pa_hi = split_u32_words(param_a)
        pb_lo, pb_hi = split_u32_words(param_b)
        records.append((var_id(dst), var_id(src), flag_lo, flag_hi, pa_lo, pa_hi, pb_lo, pb_hi))
    return records


def validate_g11_header(data, off, expected_tag):
    """Validate a BRP/PLD/SAD 32-byte header at given offset."""
    tag = data[off + 9:off + 12].decode('ascii', errors='replace')
    if tag != expected_tag:
        raise CCXMergeError(
            f"Expected '{expected_tag}' tag at CCX+0x{off:05X}, got '{tag}'"
        )
    return True


def detect_variant(data, g):
    g13_off = ccx_off(g[13])
    strtab_ptr = data.u32(g13_off + 28)
    strtab_off = ccx_off(strtab_ptr)
    
    # Count STR signal entries
    n = 0
    while True:
        ptr = data.u32(strtab_off + n * 4)
        if CCX_BASE <= ptr < CCX_BASE + CCX_SIZE:
            n += 1
        else:
            break
    
    names = []
    for i in range(min(n, 25)):
        ptr = data.u32(strtab_off + i * 4)
        off = ccx_off(ptr)
        s = data[off:off + 30].split(b'\x00')[0].decode('ascii', errors='replace')
        names.append(s)
    
    if n in (80, 81) and "S.AS.MaxPress" in names:
        return "AutoSet", n
    elif n == 97 and "S.VA.StartPress" in names:
        return "VAuto", n
    elif n == 82 and "S.AV.StartPress" in names:
        return "CS_PaceWave", n
    elif n == 76 and "S.C.Press" in names and "S.AS.MaxPress" not in names:
        return "Elite", n
    else:
        return f"Unknown({n}sig)", n


def parse_g12_block(data, g):
    """Copy g[12] CSL/AEV/EVE headers and read the STR calculation count.
    
    Returns:
        headers: 72-byte header block (CSL/AEV/EVE file type headers)
        field_count: number of calculation records referenced by g[13]
        old_range: (start_off, end_off) CCX offsets of the old g[12] headers
    """
    g12_off = ccx_off(g[12])
    headers = bytes(data[g12_off:g12_off + G12_HEADER_SIZE])
    field_count = data[ccx_off(g[13]) + 8]
    return headers, field_count, (g12_off, g12_off + G12_HEADER_SIZE)


def build_g12_block(headers, var_id):
    """Build the complete relocated g[12] block.
    
    Layout:
        +0x000: 3x24B headers (from source, unchanged)
        +0x048: 116 superset field records x 10B (interleaved CSL/EVE/AEV/EXT)
        +0x4D0: 116 x 2B col1 array (chain_start)
        +0x5B8: 116 x 2B col2 array (chain_mid)
        +0x6A0: end
    
    Returns the block bytes.
    """
    buf = bytearray()
    
    buf.extend(headers)
    
    # Interleaved field records, order preserves native firmware layout
    for rec in SUPERSET_RECORDS:
        buf.extend(build_field_record(rec, var_id))
    
    for name in SUPERSET_COL1:
        buf.extend(struct.pack('<H', var_id(name)))
    
    for c2 in SUPERSET_COL2:
        buf.extend(struct.pack('<H', c2))
    
    return bytes(buf)


def build_merge_block(free_start, g12_block=None, source_data=None, g=None, var_id=None):
    """Build the complete merge data block to write into free space.
    
    Returns (block_bytes, layout) where layout contains all the
    absolute addresses needed for pointer patching.
    
    Args:
        free_start: CCX offset where free space begins
        g12_block: optional bytes for relocated g[12] block
        source_data: CCX image bytes (needed for g[28]+g[11] template extraction)
        g: globals[] array (needed for g[28]+g[11] relocation)
        var_id: callable mapping UART variable names to target firmware var_ids
    """
    if var_id is None:
        raise CCXMergeError("build_merge_block requires a UART-name resolver")

    brp_signals = resolve_signal_specs(BRP_SIGNALS, var_id)
    pld_signals = resolve_signal_specs(PLD_SIGNALS, var_id)
    sad_signals = resolve_signal_specs(SAD_SIGNALS, var_id)

    buf = bytearray()
    base_addr = ccx_addr(free_start)
    
    layout = {}
    
    def cur_addr():
        return base_addr + len(buf)
    
    def align4():
        while len(buf) % 4 != 0:
            buf.append(0x00)
    
    # Collect all unique strings, write once, map name -> address
    all_strings = set()
    for name, _, _ in BRP_SIGNALS:
        all_strings.add(name)
    for name, _, _ in PLD_SIGNALS:
        all_strings.add(name)
    for name, _, _ in SAD_SIGNALS:
        all_strings.add(name)
    for name in STR_SIGNAL_NAMES:
        all_strings.add(name)
    
    str_addrs = {}
    layout['strings_start'] = cur_addr()
    for name in sorted(all_strings):
        str_addrs[name] = cur_addr()
        buf.extend(name.encode('ascii'))
        buf.append(0x00)
    align4()
    layout['strings_end'] = cur_addr()

    # BRP string pointer table
    layout['brp_str_ptrs'] = cur_addr()
    for name, _, _ in BRP_SIGNALS:
        buf.extend(struct.pack('<I', str_addrs[name]))
    
    # PLD string pointer table
    layout['pld_str_ptrs'] = cur_addr()
    for name, _, _ in PLD_SIGNALS:
        buf.extend(struct.pack('<I', str_addrs[name]))
    
    # SAD string pointer table
    layout['sad_str_ptrs'] = cur_addr()
    for name, _, _ in SAD_SIGNALS:
        buf.extend(struct.pack('<I', str_addrs[name]))
    
    # STR string pointer table
    layout['str_ptrs'] = cur_addr()
    for name in STR_SIGNAL_NAMES:
        buf.extend(struct.pack('<I', str_addrs[name]))
    # Terminator
    buf.extend(struct.pack('<I', 0xFFFFFFFF))
    layout['str_ptrs_end'] = cur_addr()
    
    # g[12] CSL/AEV/EVE relocated block
    if g12_block is not None:
        align4()
        layout['g12_block'] = cur_addr()
        buf.extend(g12_block)
        layout['g12_block_end'] = cur_addr()
        layout['g12_block_size'] = len(g12_block)
    
    # g[12] header gap arrays 
    # Contiguous: CSL[4] + AEV[2] + EVE[4] = 10 u16 entries = 20 bytes.
    align4()
    layout['gap_csl'] = cur_addr()
    for name in G12_GAP_CSL:
        buf.extend(struct.pack('<H', var_id(name)))
    layout['gap_aev'] = cur_addr()
    for name in G12_GAP_AEV:
        buf.extend(struct.pack('<H', var_id(name)))
    layout['gap_eve'] = cur_addr()
    for name in G12_GAP_EVE:
        buf.extend(struct.pack('<H', var_id(name)))

    if g12_block is not None:
        for i, (key, names) in enumerate((('gap_csl', G12_GAP_CSL),
                                          ('gap_aev', G12_GAP_AEV),
                                          ('gap_eve', G12_GAP_EVE))):
            off = layout['g12_block'] - base_addr + i * 24
            buf[off + 8] = len(names)
            struct.pack_into('<I', buf, off + 16, layout[key])
    
    # g[28] + g[11] combined block (OXH header + inline arrays + signal headers)
    # g[11] headers sit at the tail of the g[28] block.
    #
    # Layout:
    #   OXH header (20B) - copied from source, +8/+12 ptrs fixed to inline arrays
    #   OXH var_ids [6] (12B)
    #   OXH rates [6]   (12B)
    #   BRP var_ids [4]  (8B)
    #   BRP samples [4]  (8B)
    #   PLD var_ids [15] (30B)
    #   PLD samples [15] (30B)
    #   SAD var_ids [3+pad] (8B)
    #   SAD samples [3+pad] (8B)
    #   g[11] BRP header (32B) - ptr1/ptr2 -> inline above, ptr3 -> merge block str ptrs
    #   g[11] PLD header (32B)
    #   g[11] SAD header (32B)
    #
    if source_data is not None and g is not None:
        OXH_HDR_SIZE = 20
        G11_HDR_SIZE = 32
        
        g28_off = ccx_off(g[28])
        g11_off = ccx_off(g[11])
        
        align4()
        layout['g28_block'] = cur_addr()
        g28_buf_start = len(buf)
        
        # Copy OXH header (20 bytes) from source
        buf.extend(source_data[g28_off:g28_off + OXH_HDR_SIZE])
        
        # Relocate OXH var_id and rate arrays.
        # Follow the source pointers rather than assuming adjacency to g[28].
        oxh_count = source_data[g28_off]
        oxh_p1 = ccx_off(source_data.u32(g28_off + 8))
        oxh_p2 = ccx_off(source_data.u32(g28_off + 12))

        layout['g28_oxh_var_ids'] = cur_addr()
        buf.extend(source_data[oxh_p1:oxh_p1 + oxh_count * 2])
        layout['g28_oxh_rates'] = cur_addr()
        buf.extend(source_data[oxh_p2:oxh_p2 + oxh_count * 2])

        # Fix OXH header +8/+12 to point to relocated arrays
        struct.pack_into('<I', buf, g28_buf_start + 8, layout['g28_oxh_var_ids'])
        struct.pack_into('<I', buf, g28_buf_start + 12, layout['g28_oxh_rates'])

        # Inline BRP var_ids + samples
        layout['g28_brp_var_ids'] = cur_addr()
        for _, vid, _ in brp_signals:
            buf.extend(struct.pack('<H', vid))
        layout['g28_brp_samples'] = cur_addr()
        for _, _, samples in brp_signals:
            buf.extend(struct.pack('<H', samples))
        
        # Inline PLD var_ids + samples
        layout['g28_pld_var_ids'] = cur_addr()
        for _, vid, _ in pld_signals:
            buf.extend(struct.pack('<H', vid))
        layout['g28_pld_samples'] = cur_addr()
        for _, _, samples in pld_signals:
            buf.extend(struct.pack('<H', samples))
        
        # Inline SAD var_ids + samples
        layout['g28_sad_var_ids'] = cur_addr()
        for _, vid, _ in sad_signals:
            buf.extend(struct.pack('<H', vid))
        buf.extend(struct.pack('<H', 0x0000))
        layout['g28_sad_samples'] = cur_addr()
        for _, _, samples in sad_signals:
            buf.extend(struct.pack('<H', samples))
        buf.extend(struct.pack('<H', 0x0000))
        
        # g[11] headers - copy templates from source, then fix pointers in-place
        layout['g11_block'] = cur_addr()
        
        for h, (tag, vid_key, samp_key, str_key, signals) in enumerate([
            ('BRP', 'g28_brp_var_ids', 'g28_brp_samples', 'brp_str_ptrs', brp_signals),
            ('PLD', 'g28_pld_var_ids', 'g28_pld_samples', 'pld_str_ptrs', pld_signals),
            ('SAD', 'g28_sad_var_ids', 'g28_sad_samples', 'sad_str_ptrs', sad_signals),
        ]):
            hdr_src = g11_off + h * G11_HDR_SIZE
            hdr_start = len(buf)
            buf.extend(source_data[hdr_src:hdr_src + G11_HDR_SIZE])
            
            # Fix count
            buf[hdr_start + 8] = len(signals)
            # Fix ptr1 -> inline var_ids
            struct.pack_into('<I', buf, hdr_start + 16, layout[vid_key])
            # Fix ptr2 -> inline samples
            struct.pack_into('<I', buf, hdr_start + 20, layout[samp_key])
            # Fix ptr3 -> merge block string ptrs
            struct.pack_into('<I', buf, hdr_start + 28, layout[str_key])
        
        layout['g28_block_end'] = cur_addr()
    
    # g[21] history-summary rules
    # AS=13, VA/CP=20, AV=17 records. Superset=21
    align4()
    layout['g21_records'] = cur_addr()
    for rec_tuple in resolve_g20_records(var_id):
        for v in rec_tuple:
            buf.extend(struct.pack('<H', v))
    layout['g21_records_end'] = cur_addr()
    
    # STR header, NPD IDs and NPD header. Read each object through its
    # descriptor; intervening data is not part of either header.
    if source_data is not None and g is not None:
        align4()
        g13_src = ccx_off(g[13])
        layout['g13_block'] = cur_addr()
        g13_start = len(buf)
        buf.extend(source_data[g13_src:g13_src + 36])
        g14_src = ccx_off(g[14])
        npd_ids = ccx_off(source_data.u32(g14_src + 24))
        npd_count = source_data[g14_src + 16]
        if npd_count not in (7, 8):
            raise CCXMergeError(f"Unsupported NPD signal count: {npd_count}")
        buf.extend(source_data[npd_ids:npd_ids + 14])
        buf.extend(struct.pack('<H', var_id('AIE')))
        buf.extend(source_data[g14_src:g14_src + 28])
        
        # g[13]+0x08: field record count
        buf[g13_start + 0x08] = SUPERSET_FIELD_COUNT
        # g[13]+0x10: chain_start ptr -> col1 in relocated g[12]
        if 'g12_block' in layout:
            chain_start = layout['g12_block'] + G12_HEADER_SIZE + SUPERSET_FIELD_COUNT * 10
            chain_mid = chain_start + SUPERSET_FIELD_COUNT * 2
            field_recs = layout['g12_block'] + G12_HEADER_SIZE
            struct.pack_into('<I', buf, g13_start + 0x10, chain_start)
            struct.pack_into('<I', buf, g13_start + 0x14, chain_mid)
            struct.pack_into('<I', buf, g13_start + 0x20, field_recs)
        # g[13]+0x1C: strtab ptr -> STR signal name pointer table
        struct.pack_into('<I', buf, g13_start + 0x1C, layout['str_ptrs'])
        # g[13]+0x32: var_id unmask
        for off, expected in PSTR_VARID_MASKS.items():
            struct.pack_into('<H', buf, g13_start + off, var_id(expected))
        # g[13]+0x44 = g[14]+0x10: NPD count
        buf[g13_start + 0x44] = PSTR_NPD_SUPERSET_COUNT
        # g[14]+0x18: back-pointer to g[13]+0x24
        struct.pack_into('<I', buf, g13_start + 0x34 + 0x18, layout['g13_block'] + 0x24)
        
        layout['g14_block'] = layout['g13_block'] + 52  # g[14] immediately follows
        layout['g13g14_end'] = cur_addr()
    
    # g[21] header (8B)
    # {count(u16), pad(u16), ptr(u32)}
    if source_data is not None and g is not None:
        align4()
        layout['g21_block'] = cur_addr()
        buf.extend(struct.pack('<HHI', G20_SUPERSET_COUNT, 0, layout['g21_records']))
        layout['g21_block_end'] = cur_addr()
    
    # g[26]+g[27] consolidated block
    # g[26]: 8 records x 20B = 160B (unchanged arrays remain shared)
    #        + superset tail: APN(4B) + CSN(4B) + BRH(8B) = 16B
    # g[27]: 3 records x 16B = 48B (APN/CSN/BRH with counts+ptrs into g[26] tail)
    if source_data is not None and g is not None:
        align4()
        g26_src = ccx_off(g[26])
        layout['g26_block'] = cur_addr()
        g26_start = len(buf)
        
        # Copy 160B of g[26] records, then patch counts and relocate data arrays
        buf.extend(source_data[g26_src:g26_src + 160])
        
        for rec_idx, (sup_var_names, sup_rates) in G26_DATA_PATCHES.items():
            rec_buf_off = g26_start + rec_idx * 20
            new_count = len(sup_var_names)
            buf[rec_buf_off] = new_count
            
            # Write superset arrays into merge block
            layout[f'g26_r{rec_idx}_varids'] = cur_addr()
            for name in sup_var_names:
                buf.extend(struct.pack('<H', var_id(name)))
            layout[f'g26_r{rec_idx}_rates'] = cur_addr()
            for v in sup_rates:
                buf.extend(struct.pack('<H', v))
            
            # Redirect record ptr1/ptr2 to new arrays
            struct.pack_into('<I', buf, rec_buf_off + 8, layout[f'g26_r{rec_idx}_varids'])
            struct.pack_into('<I', buf, rec_buf_off + 12, layout[f'g26_r{rec_idx}_rates'])
        
        tail_start = len(buf)
        layout['g26_tail_apn'] = cur_addr()
        for name in G26_TAIL_APN:
            buf.extend(struct.pack('<H', var_id(name)))
        layout['g26_tail_csn'] = cur_addr()
        for name in G26_TAIL_CSN:
            buf.extend(struct.pack('<H', var_id(name)))
        layout['g26_tail_brh'] = cur_addr()
        for name in G26_TAIL_BRH:
            buf.extend(struct.pack('<H', var_id(name)))
        
        layout['g27_block'] = cur_addr()
        g27_src = ccx_off(g[27])
        g27_start = len(buf)
        buf.extend(source_data[g27_src:g27_src + 48])
        
        # Fix counts and pointers in g[27] records
        for r, (superset_cnt, tail_key) in enumerate([
            (G27_APN_SUPERSET_COUNT, 'g26_tail_apn'),
            (G27_CSN_SUPERSET_COUNT, 'g26_tail_csn'),
            (G27_BRH_SUPERSET_COUNT, 'g26_tail_brh'),
        ]):
            rec_off = g27_start + r * 16
            buf[rec_off] = superset_cnt
            struct.pack_into('<I', buf, rec_off + 8, layout[tail_key])

        layout['g26_tail_end'] = cur_addr()
        layout['g26g27_end'] = cur_addr()
    
    
    layout['total_size'] = len(buf)
    layout['expected_block'] = bytes(buf)
    return bytes(buf), layout

def apply_patches(data, g, layout, name_lookup):
    """Patch the CCX image to use the new merge block.
    
    Structs and their pointer fixups are pre-built in the merge block.
    Only globals[] pointers and variable ACT flags are changed in place.
    """
    patches = []
    globals_off = 0x108
    
    # Redirect globals[28] -> new g[28] block
    # Redirect globals[11] -> new g[11] headers (inside g[28] block)
    if 'g28_block' in layout:
        old_g28 = data.u32(globals_off + 28 * 4)
        patches.append(f"globals[28]: 0x{old_g28:08X} -> 0x{layout['g28_block']:08X}")
        data.write_u32(globals_off + 28 * 4, layout['g28_block'])
        
        old_g11 = data.u32(globals_off + 11 * 4)
        patches.append(f"globals[11]: 0x{old_g11:08X} -> 0x{layout['g11_block']:08X}")
        data.write_u32(globals_off + 11 * 4, layout['g11_block'])
        
        patches.append(f"BRP sig_count -> {len(BRP_SIGNALS)} (in new g[11])")
        patches.append(f"PLD sig_count -> {len(PLD_SIGNALS)} (in new g[11])")
    
    # Redirect globals[12] -> new g[12] block
    if 'g12_block' in layout:
        old_g12 = data.u32(globals_off + 12 * 4)
        patches.append(f"globals[12]: 0x{old_g12:08X} -> 0x{layout['g12_block']:08X}")
        data.write_u32(globals_off + 12 * 4, layout['g12_block'])
    
    
    # Redirect globals[13] + globals[14] -> consolidated block
    # All PSTR patches (strtab, field_rec_count, chain ptrs, var_id unmask,
    # NPD count, g[14] back-pointer) are pre-applied in the merge block copy.
    if 'g13_block' in layout:
        old_g13 = data.u32(globals_off + 13 * 4)
        patches.append(f"globals[13]: 0x{old_g13:08X} -> 0x{layout['g13_block']:08X}")
        data.write_u32(globals_off + 13 * 4, layout['g13_block'])
        
        old_g14 = data.u32(globals_off + 14 * 4)
        patches.append(f"globals[14]: 0x{old_g14:08X} -> 0x{layout['g14_block']:08X}")
        data.write_u32(globals_off + 14 * 4, layout['g14_block'])
    
    
    # Redirect globals[21] -> pre-built header
    if 'g21_block' in layout:
        old_g21 = data.u32(globals_off + 21 * 4)
        patches.append(f"globals[21]: 0x{old_g21:08X} -> 0x{layout['g21_block']:08X}")
        data.write_u32(globals_off + 21 * 4, layout['g21_block'])
    
    # Redirect globals[26] + globals[27] -> consolidated block
    # TCE/PBT counts, g[27] APN/CSN/BRH counts+ptrs all pre-applied.
    if 'g26_block' in layout:
        old_g26 = data.u32(globals_off + 26 * 4)
        patches.append(f"globals[26]: 0x{old_g26:08X} -> 0x{layout['g26_block']:08X}")
        data.write_u32(globals_off + 26 * 4, layout['g26_block'])
        
        old_g27 = data.u32(globals_off + 27 * 4)
        patches.append(f"globals[27]: 0x{old_g27:08X} -> 0x{layout['g27_block']:08X}")
        data.write_u32(globals_off + 27 * 4, layout['g27_block'])
    
    # Patch g[4] ACT flags
    act_count = 0
    g4_records = descriptor_record_offsets(data, g, name_lookup, 4, 28, G4_ACT_PATCHES, expected_base=0x001E)
    for name in G4_ACT_PATCHES:
        rec_off = g4_records[name]
        old_flags = data.u16(rec_off)
        if not (old_flags & 0x0001):
            data.write_u16(rec_off, old_flags | 0x0001)
            act_count += 1
    if act_count:
        patches.append(f"g[4] ACT bit0: {act_count}/{len(G4_ACT_PATCHES)} records activated")
    
    # Patch g[8] ACT flags
    g8_act_count = 0
    g8_records = descriptor_record_offsets(data, g, name_lookup, 8, 20, G8_ACT_PATCHES, expected_base=0x020D)
    for name in G8_ACT_PATCHES:
        rec_off = g8_records[name]
        old_flags = data.u16(rec_off)
        if not (old_flags & 0x0001):
            data.write_u16(rec_off, old_flags | 0x0001)
            g8_act_count += 1
    if g8_act_count:
        patches.append(f"g[8] ACT bit0: {g8_act_count}/{len(G8_ACT_PATCHES)} records activated")

    return patches


def validate_result(data, g, layout, var_id, name_lookup):
    """Post-patch validation.
    
    After apply_patches, globals[] pointers have been redirected to the merge block.
    Read current pointers from data, not from the pre-patch `g` dict.
    """
    errors = []
    globals_off = 0x108

    block_off = ccx_off(layout['strings_start'])
    if bytes(data[block_off:block_off + layout['total_size']]) != layout['expected_block']:
        errors.append("Merge block differs from the planned descriptors, arrays or labels")
    
    # Read current globals[] (post-patch)
    cur_g = {}
    for i in range(29):
        cur_g[i] = data.u32(globals_off + i * 4)
    
    # g[11] / g[28]: BRP/PLD signal counts
    g11_off = ccx_off(cur_g[11])
    if data[g11_off + 8] != len(BRP_SIGNALS):
        errors.append(f"BRP sig_count = {data[g11_off+8]}, expected {len(BRP_SIGNALS)}")
    if data[g11_off + 32 + 8] != len(PLD_SIGNALS):
        errors.append(f"PLD sig_count = {data[g11_off+32+8]}, expected {len(PLD_SIGNALS)}")
    for h, (tag, specs) in enumerate([
        ('BRP', BRP_SIGNALS),
        ('PLD', PLD_SIGNALS),
        ('SAD', SAD_SIGNALS),
    ]):
        hdr_off = g11_off + h * 32
        actual_count = data[hdr_off + 8]
        expected = resolve_signal_specs(specs, var_id)
        if actual_count != len(expected):
            errors.append(f"{tag} sig_count = {actual_count}, expected {len(expected)}")
            continue
        ids_ptr = data.u32(hdr_off + 16)
        ids_off = ccx_off(ids_ptr)
        actual_ids = [data.u16(ids_off + i * 2) for i in range(len(expected))]
        expected_ids = [vid for _, vid, _ in expected]
        if actual_ids != expected_ids:
            errors.append(f"{tag} var_ids = {actual_ids!r}, expected {expected_ids!r}")
    
    # g[13]: PSTR record
    g13_off = ccx_off(cur_g[13])
    
    # STR signal name table pointer
    strtab_ptr = data.u32(g13_off + 28)
    if strtab_ptr != layout['str_ptrs']:
        errors.append(f"PSTR strtab pointer mismatch: 0x{strtab_ptr:08X} vs 0x{layout['str_ptrs']:08X}")
    else:
        first_str_ptr = data.u32(ccx_off(strtab_ptr))
        first_str_off = ccx_off(first_str_ptr)
        s = data[first_str_off:first_str_off + 10].split(b'\x00')[0].decode('ascii', errors='replace')
        if s != STR_SIGNAL_NAMES[0]:
            errors.append(f"First STR signal = '{s}', expected '{STR_SIGNAL_NAMES[0]}'")
    
    # Field record count
    actual_str_count = data[g13_off + 0x08]
    if actual_str_count != SUPERSET_FIELD_COUNT:
        errors.append(f"PSTR field_rec_count = {actual_str_count}, expected {SUPERSET_FIELD_COUNT}")
    
    # STR table terminator
    term_off = ccx_off(layout['str_ptrs']) + len(STR_SIGNAL_NAMES) * 4
    term = data.u32(term_off)
    if term != 0xFFFFFFFF:
        errors.append(f"STR table terminator = 0x{term:08X}, expected 0xFFFFFFFF")
    
    # g[13] -> g[12] internal pointers
    if 'g12_block' in layout:
        new_g12 = layout['g12_block']
        expected_fr = new_g12 + G12_HEADER_SIZE
        expected_chain = new_g12 + G12_HEADER_SIZE + SUPERSET_FIELD_COUNT * 10
        expected_mid = expected_chain + SUPERSET_FIELD_COUNT * 2
        
        actual_fr = data.u32(g13_off + 0x20)
        if actual_fr != expected_fr:
            errors.append(f"PSTR field_recs ptr = 0x{actual_fr:08X}, expected 0x{expected_fr:08X}")
        actual_chain = data.u32(g13_off + 0x10)
        if actual_chain != expected_chain:
            errors.append(f"PSTR chain_start ptr = 0x{actual_chain:08X}, expected 0x{expected_chain:08X}")
        actual_mid = data.u32(g13_off + 0x14)
        if actual_mid != expected_mid:
            errors.append(f"PSTR chain_mid ptr = 0x{actual_mid:08X}, expected 0x{expected_mid:08X}")
        col1_off = ccx_off(expected_chain)
        actual_col1 = [data.u16(col1_off + i * 2) for i in range(SUPERSET_FIELD_COUNT)]
        expected_col1 = [var_id(name) for name in SUPERSET_COL1]
        if actual_col1 != expected_col1:
            for i, (actual, expected) in enumerate(zip(actual_col1, expected_col1)):
                if actual != expected:
                    errors.append(
                        f"PSTR col1[{i}] = 0x{actual:04X}, expected 0x{expected:04X}")
                    break
    
    # PSTR var_id unmask
    for off, expected in PSTR_VARID_MASKS.items():
        actual = data.u16(g13_off + off)
        expected_id = var_id(expected)
        if actual != expected_id:
            errors.append(f"PSTR +0x{off:02X} var_id = 0x{actual:04X}, expected 0x{expected_id:04X}")
    
    # NPD count in g[13] (at +0x44 = g[14]+0x10 offset from g[13] start)
    npd_count = data[g13_off + PSTR_NPD_COUNT_OFF]
    if npd_count < PSTR_NPD_SUPERSET_COUNT:
        errors.append(f"PSTR NPD count = {npd_count}, expected >= {PSTR_NPD_SUPERSET_COUNT}")
    
    # g[14]: NPD count + back-pointer
    g14_off = ccx_off(cur_g[14])
    npd14 = data[g14_off + 16]
    if npd14 < G14_NPD_SUPERSET_COUNT:
        errors.append(f"g[14] NPD count = {npd14}, expected >= {G14_NPD_SUPERSET_COUNT}")
    
    # g[14]+0x18 back-pointer should reference g[13]+0x24
    backptr = data.u32(g14_off + 0x18)
    expected_backptr = cur_g[13] + 0x24
    if backptr != expected_backptr:
        errors.append(f"g[14] back-pointer = 0x{backptr:08X}, expected 0x{expected_backptr:08X}")
    
    
    # g[12]: relocated block
    if 'g12_block' in layout:
        actual_g12 = cur_g[12]
        if actual_g12 != layout['g12_block']:
            errors.append(f"globals[12] = 0x{actual_g12:08X}, expected 0x{layout['g12_block']:08X}")
        
        new_g12_off = ccx_off(layout['g12_block'])
        tag_csl = data[new_g12_off + 9:new_g12_off + 12].decode('ascii', errors='replace')
        tag_aev = data[new_g12_off + 24 + 9:new_g12_off + 24 + 12].decode('ascii', errors='replace')
        tag_eve = data[new_g12_off + 48 + 9:new_g12_off + 48 + 12].decode('ascii', errors='replace')
        if tag_csl != "CSL":
            errors.append(f"New g[12] CSL tag = '{tag_csl}', expected 'CSL'")
        if tag_aev != "AEV":
            errors.append(f"New g[12] AEV tag = '{tag_aev}', expected 'AEV'")
        if tag_eve != "EVE":
            errors.append(f"New g[12] EVE tag = '{tag_eve}', expected 'EVE'")
        
        for h, (tag, names) in enumerate([
            ('CSL', G12_GAP_CSL),
            ('AEV', G12_GAP_AEV),
            ('EVE', G12_GAP_EVE),
        ]):
            hdr_off = new_g12_off + h * 24
            actual_count = data[hdr_off + 8]
            if actual_count != len(names):
                errors.append(f"g[12] {tag} gap count = {actual_count}, expected {len(names)}")
                continue
            ptr = data.u32(hdr_off + 16)
            gap_off = ccx_off(ptr)
            actual_ids = [data.u16(gap_off + i * 2) for i in range(len(names))]
            expected_ids = [var_id(name) for name in names]
            if actual_ids != expected_ids:
                errors.append(f"g[12] {tag} gap ids = {actual_ids!r}, expected {expected_ids!r}")

        # Count field records
        fr_start = new_g12_off + G12_HEADER_SIZE
        field_count = 0
        for i in range(200):
            off = fr_start + i * 10
            if off + 10 > len(data):
                break
            typ = data[off]
            fid = data[off + 1]
            vid = data.u16(off + 2)
            if typ == 0x0D and fid in (0, 1, 2, 3):
                field_count += 1
            elif typ == 0x00 and fid in (0, 1, 2, 3) and vid == 0x7FFF:
                field_count += 1
            else:
                break
        if field_count != SUPERSET_FIELD_COUNT:
            errors.append(f"New g[12] has {field_count} field records, expected {SUPERSET_FIELD_COUNT}")
        expected_records = b''.join(build_field_record(rec, var_id) for rec in SUPERSET_RECORDS)
        actual_records = bytes(data[fr_start:fr_start + len(expected_records)])
        if actual_records != expected_records:
            for i in range(SUPERSET_FIELD_COUNT):
                start = i * 10
                if actual_records[start:start + 10] != expected_records[start:start + 10]:
                    errors.append(f"New g[12] field record[{i}] differs from resolved superset")
                    break
    
    # Check BRP ptr chain
    brp_ptr3 = data.u32(g11_off + 28)
    first_brp_str_ptr = data.u32(ccx_off(brp_ptr3))
    first_brp_str = data[ccx_off(first_brp_str_ptr):ccx_off(first_brp_str_ptr)+20].split(b'\x00')[0]
    if first_brp_str.decode('ascii', errors='replace') != BRP_SIGNALS[0][0]:
        errors.append(f"First BRP string = '{first_brp_str}', expected '{BRP_SIGNALS[0][0]}'")
    
    # g[21]: computation table
    g21_off = ccx_off(cur_g[21])
    g21_count = data.u16(g21_off)
    g21_ptr = data.u32(g21_off + 4)
    if g21_count != G20_SUPERSET_COUNT:
        errors.append(f"g[21] comp count = {g21_count}, expected {G20_SUPERSET_COUNT}")
    if g21_ptr != layout['g21_records']:
        errors.append(f"g[21] comp ptr = 0x{g21_ptr:08X}, expected 0x{layout['g21_records']:08X}")
    
    # g[26]: record counts and data array pointers
    g26_off = ccx_off(cur_g[26])
    for rec_idx, (sup_var_names, sup_rates) in G26_DATA_PATCHES.items():
        expected_count = len(sup_var_names)
        rec_off = g26_off + rec_idx * 20
        actual_count = data[rec_off]
        tag = data[rec_off + 1:rec_off + 4].decode('ascii', errors='replace')
        if actual_count != expected_count:
            errors.append(f"g[26] {tag} count = {actual_count}, expected {expected_count}")
        # Verify ptr1/ptr2 point into merge block (relocated arrays)
        ptr_key = f'g26_r{rec_idx}_varids'
        if ptr_key in layout:
            actual_ptr1 = data.u32(rec_off + 8)
            if actual_ptr1 != layout[ptr_key]:
                errors.append(f"g[26] {tag} ptr1 = 0x{actual_ptr1:08X}, expected 0x{layout[ptr_key]:08X}")
            rate_key = f'g26_r{rec_idx}_rates'
            actual_ptr2 = data.u32(rec_off + 12)
            if actual_ptr2 != layout[rate_key]:
                errors.append(f"g[26] {tag} ptr2 = 0x{actual_ptr2:08X}, expected 0x{layout[rate_key]:08X}")
            if actual_ptr1 == layout[ptr_key]:
                ids_off = ccx_off(actual_ptr1)
                actual_ids = [data.u16(ids_off + i * 2) for i in range(expected_count)]
                expected_ids = [var_id(name) for name in sup_var_names]
                if actual_ids != expected_ids:
                    errors.append(f"g[26] {tag} var_ids = {actual_ids!r}, expected {expected_ids!r}")
    
    # g[27]: record counts and pointers
    g27_off = ccx_off(cur_g[27])
    for r, (tag, expected_cnt, tail_key) in enumerate([
        ('APN', G27_APN_SUPERSET_COUNT, 'g26_tail_apn'),
        ('CSN', G27_CSN_SUPERSET_COUNT, 'g26_tail_csn'),
        ('BRH', G27_BRH_SUPERSET_COUNT, 'g26_tail_brh'),
    ]):
        rec_off = g27_off + r * 16
        actual_cnt = data[rec_off]
        if actual_cnt != expected_cnt:
            errors.append(f"g[27] {tag} count = {actual_cnt}, expected {expected_cnt}")
        if tail_key in layout:
            actual_ptr = data.u32(rec_off + 8)
            if actual_ptr != layout[tail_key]:
                errors.append(f"g[27] {tag} ptr = 0x{actual_ptr:08X}, expected 0x{layout[tail_key]:08X}")
            else:
                names = {
                    'APN': G26_TAIL_APN,
                    'CSN': G26_TAIL_CSN,
                    'BRH': G26_TAIL_BRH,
                }[tag]
                ids_off = ccx_off(actual_ptr)
                actual_ids = [data.u16(ids_off + i * 2) for i in range(len(names))]
                expected_ids = [var_id(name) for name in names]
                if actual_ids != expected_ids:
                    errors.append(f"g[27] {tag} var_ids = {actual_ids!r}, expected {expected_ids!r}")
    
    # The allocator leaves the region CRC outside the merge block.
    if ccx_off(layout['strings_start']) + layout['total_size'] > CCX_CRC_OFFSET:
        errors.append("Merge block overlaps the CCX CRC")
    
    # globals[] pointer consistency
    check_globals = [
        (11, 'g11_block'), (12, 'g12_block'), (28, 'g28_block'),
        (13, 'g13_block'), (14, 'g14_block'),
        (26, 'g26_block'), (27, 'g27_block'),
        (21, 'g21_block'),
    ]
    
    for idx, key in check_globals:
        if key in layout:
            actual = cur_g[idx]
            if actual != layout[key]:
                errors.append(f"globals[{idx}] = 0x{actual:08X}, expected 0x{layout[key]:08X}")
    
    # Unchanged objects retain both their addresses and contents, including
    # EEPROM group member pointers and the UART name lookup.
    for off, expected in layout.get('preserved_ranges', []):
        if bytes(data[off:off + len(expected)]) != expected:
            errors.append(f"Unchanged CCX range at +0x{off:05X} was modified")
    
    # g[4] ACT flags
    act_mismatches = 0
    g4_records = descriptor_record_offsets(data, g, name_lookup, 4, 28, G4_ACT_PATCHES, expected_base=0x001E)
    for name in G4_ACT_PATCHES:
        rec_off = g4_records[name]
        actual = data.u16(rec_off)
        if not (actual & 0x0001):
            act_mismatches += 1
    if act_mismatches:
        errors.append(f"g[4] ACT bit0: {act_mismatches} records missing ACT")
    
    # g[8] ACT flags
    g8_mismatches = 0
    g8_records = descriptor_record_offsets(data, g, name_lookup, 8, 20, G8_ACT_PATCHES, expected_base=0x020D)
    for name in G8_ACT_PATCHES:
        rec_off = g8_records[name]
        actual = data.u16(rec_off)
        if not (actual & 0x0001):
            g8_mismatches += 1
    if g8_mismatches:
        errors.append(f"g[8] ACT bit0: {g8_mismatches} records missing ACT")

    return errors


def stream_objects(data, g):
    """Return exact byte ranges owned by the SX567 stream descriptors we replace.

    Arrays may overlap or be shared. Padding and intervening objects are not
    owned by a descriptor merely because they follow its header.
    """
    spans = set()

    def add(addr, size):
        off = ccx_off(addr)
        if size < 0 or off + size > CCX_CRC_OFFSET:
            raise CCXMergeError(f"Stream object at 0x{addr:08X} exceeds CCX data")
        if size:
            spans.add((off, off + size))
        return off

    def array(slot, count, stride):
        return add(data.u32(slot), count * stride) if count else None

    for idx, records, stride in ((11, 3, 32), (12, 3, 24), (13, 1, 36),
                                 (26, 8, 20), (27, 3, 16), (28, 1, 20)):
        base = add(g[idx], records * stride)
        for i in range(records):
            off = base + i * stride
            count = data[off + 8] if idx in (11, 12, 13) else data[off]
            if idx in (11, 12, 13):
                array(off + 16, count, 2)
            else:
                array(off + 8, count, 2)
            if idx in (26, 28):
                array(off + 12, count, 2)
            if idx in (11, 13):
                array(off + 20, count, 2)
                labels = array(off + 28, count, 4)
                for j in range(count):
                    addr = data.u32(labels + j * 4)
                    start = ccx_off(addr)
                    end = data.find(b'\x00', start, CCX_CRC_OFFSET)
                    if end < 0:
                        raise CCXMergeError(f"Unterminated EDF label at 0x{addr:08X}")
                    add(addr, end - start + 1)
                if idx == 13:
                    array(off + 32, count, 10)
                    if data.u32(labels + count * 4) == 0xFFFFFFFF:
                        add(ccx_addr(labels + count * 4), 4)

    off = add(g[14], 28)
    array(off + 24, data[off + 16], 2)
    off = add(g[21], 8)
    array(off + 4, data.u32(off), 16)
    return spans


def mask_ranges(mask, value):
    """Yield contiguous ranges marked with the requested byte value."""
    start = 0
    while start < len(mask):
        start = mask.find(bytes([value]), start)
        if start < 0:
            break
        end = start + 1
        while end < len(mask) and mask[end] == value:
            end += 1
        yield start, end
        start = end


def reclaim_stream_objects(data, old_objects, live_objects, external_refs=()):
    """Erase replaced objects, retaining shared arrays and externally referenced data."""
    retired = bytearray(len(data))
    for start, end in old_objects:
        retired[start:end] = b'\x01' * (end - start)
    owned = bytes(retired)
    for start, end in live_objects:
        retired[start:end] = b'\x00' * (end - start)

    # A previous patch may have added another reference to an old object.
    # Retaining its whole target also makes its outgoing references live.
    # This scan only prevents erasure; it never interprets or rewrites words.
    refs = [(off, data.u32(off) - CCX_BASE)
            for off in range(0, len(data) - 3, 2)
            if CCX_BASE <= data.u32(off) < CCX_BASE + CCX_CRC_OFFSET]
    refs.extend((None, target) for target in external_refs if 0 <= target < len(data))
    changed = True
    while changed:
        changed = False
        for slot, target in refs:
            if owned[target] and (slot is None or not any(retired[slot:slot + 4])):
                for start, end in old_objects:
                    if start <= target < end and any(retired[start:end]):
                        retired[start:end] = b'\x00' * (end - start)
                        changed = True

    for start, end in mask_ranges(retired, 1):
        data[start:end] = b'\xFF' * (end - start)
    return retired


def merge_ccx_region(ccx, g, var_id, name_lookup, allocate, force=False, verbose=False,
                     external_refs=()):
    """Merge universal EDF signals into a CCX bytearray."""
    target = ccx
    ccx = CCXImage(ccx)

    def log(msg):
        if verbose:
            print(msg)

    variant, sig_count = detect_variant(ccx, g)
    log("EDF merge: %s (%d STR signals)" % (variant, sig_count))

    if variant.startswith("Unknown") and not force:
        raise CCXMergeError("Unknown variant '%s'. Use force=True to proceed." % variant)

    # Capture old signal counts before patching
    g11_off = ccx_off(g[11])
    old_brp = ccx[g11_off + 8]
    old_pld = ccx[g11_off + 32 + 8]
    old_sad = ccx[g11_off + 64 + 8]
    old_g21 = ccx.u16(ccx_off(g[21]))

    g12_headers, old_g12_field_count, old_g12_range = parse_g12_block(ccx, g)
    g12_block = build_g12_block(g12_headers, var_id)
    log("  g[12]: %d -> %d field records (%dB)" % (old_g12_field_count, SUPERSET_FIELD_COUNT, len(g12_block)))

    original = bytes(ccx)
    old_objects = stream_objects(ccx, g)
    # Build once to measure, then use the same allocator as other CCX patches.
    merge_block, _ = build_merge_block(0, g12_block, ccx, g, var_id)
    merge_start = allocate(len(merge_block))
    if merge_start % 4 or not 0 <= merge_start <= CCX_CRC_OFFSET - len(merge_block):
        raise CCXMergeError("Invalid merge allocation")
    if ccx[merge_start:merge_start + len(merge_block)] != b'\xFF' * len(merge_block):
        raise CCXMergeError("Merge allocation is not erased")
    merge_block, layout = build_merge_block(merge_start, g12_block, ccx, g, var_id)
    log("  merge block: %d bytes at CCX+0x%05X" % (len(merge_block), merge_start))

    ccx[merge_start:merge_start + len(merge_block)] = merge_block
    patches = apply_patches(ccx, g, layout, name_lookup)
    cur_g = [ccx.u32(0x108 + i * 4) for i in range(29)]
    changed = reclaim_stream_objects(ccx, old_objects, stream_objects(ccx, cur_g), external_refs)
    log("  reclaimed %d bytes of replaced stream objects" % sum(changed))

    # Everything outside these explicit writes must remain byte-identical.
    changed[merge_start:merge_start + len(merge_block)] = b'\x01' * len(merge_block)
    for idx in (11, 12, 13, 14, 21, 26, 27, 28):
        off = 0x108 + idx * 4
        changed[off:off + 4] = b'\x01' * 4
    for table, stride, names, base in ((4, 28, G4_ACT_PATCHES, 0x001E),
                                      (8, 20, G8_ACT_PATCHES, 0x020D)):
        offsets = descriptor_record_offsets(ccx, g, name_lookup, table, stride, names, base)
        for off in offsets.values():
            changed[off:off + 2] = b'\x01' * 2
    layout['preserved_ranges'] = [(start, original[start:end])
                                  for start, end in mask_ranges(changed, 0)]

    errors = validate_result(ccx, g, layout, var_id, name_lookup)
    if errors:
        raise CCXMergeError("Validation failed:\n  " + "\n  ".join(errors))

    target[:] = ccx
    print("EDF merge: STR %d->%d, BRP %d->%d, PLD %d->%d, g12 %d->%d, g21 %d->%d"
          % (sig_count, len(STR_SIGNAL_NAMES), old_brp, len(BRP_SIGNALS),
             old_pld, len(PLD_SIGNALS), old_g12_field_count, SUPERSET_FIELD_COUNT,
             old_g21, G20_SUPERSET_COUNT))
    return patches


def patch_edf_merge(asf, force=True, verbose=False):
    if asf.ccx_size != CCX_SIZE:
        raise CCXMergeError("CCX size is %d bytes, expected %d" % (asf.ccx_size, CCX_SIZE))

    g = [asf.FLASH_BASE + asf.globals_offset(i) for i in range(29)]
    if g[0] != CCX_BASE:
        raise CCXMergeError("globals[0] = 0x%08X, expected 0x%08X" % (g[0], CCX_BASE))

    name_lookup = asf.var_ids_by_name()

    ccx = CCXImage(asf.fw[asf.ccx_off:asf.ccx_off + asf.ccx_size])
    # Retain old objects also referenced directly by BLX/CDX or injected code.
    external_refs = (asf.read_u32(off) - CCX_BASE
                     for start, end in ((0, asf.ccx_off),
                                        (asf.ccx_off + asf.ccx_size, len(asf.fw)))
                     for off in range(start, end - 3, 2))
    patches = merge_ccx_region(
        ccx,
        g,
        asf.find_var_id_by_name,
        name_lookup,
        lambda size: asf.find_ccx_ff_range_backwards(size, alignment=4) - asf.ccx_off,
        force=force,
        verbose=verbose,
        external_refs=external_refs,
    )
    asf.patch(ccx, addr=asf.ccx_off, clobber=True)
    return patches


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Merge universal EDF signals into SX567 CCX image"
    )
    parser.add_argument("input", help="Input full AS10 firmware image")
    parser.add_argument("-o", "--output", help="Output file (default: <input>.merged.bin)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed patch list")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing")
    parser.add_argument("--force", action="store_true", help="Skip variant detection warnings")
    parser.add_argument(
        "--ignore-input-crc", action="store_true",
        help="Allow input whose firmware region CRCs are already dirty"
    )
    parser.add_argument(
        "--defer-crc", action="store_true",
        help="Leave firmware region CRCs dirty for the calling patcher to finalize"
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    with input_path.open("rb") as f:
        asf = ASFirmware(f, validate_crc=not args.ignore_input_crc)

    patches = patch_edf_merge(asf, force=args.force, verbose=args.verbose)

    if args.verbose:
        print("\nPatches (%d):" % len(patches))
        for p in patches:
            print("  %s" % p)

    if args.dry_run:
        print("DRY RUN (no output written)")
        return

    if not args.defer_crc:
        asf.fix_crcs()
    out_path = Path(args.output) if args.output else input_path.with_suffix('.merged.bin')
    out_path.write_bytes(bytes(asf.fw))


if __name__ == '__main__':
    main()
