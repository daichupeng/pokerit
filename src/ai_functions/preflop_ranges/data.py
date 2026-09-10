"""Audited RFI chart transcription.

Each action string contains the 169-grid hand classes in which that action
appears. ``mixed`` marks a class with more than one source-chart colour. The
runtime deliberately exposes acceptable actions, not invented frequencies.
"""

MTT_8MAX_40_SOURCE = {
    "UTG": {
        "raise": "AA AKs AQs AJs ATs A9s A8s A7s A6s A5s A4s A3s AKo KK KQs KJs KTs K9s K8s K7s K6s AQo KQo QQ QJs QTs Q9s AJo KJo QJo JJ JTs J9s ATo KTo TT T9s T8s 99 98s 88 77 66 55 44 22",
        "mixed": "K7s K6s QJo KTo 98s 44 22",
    },
    "UTG+1": {
        "raise": "AA AKs AQs AJs ATs A9s A8s A7s A6s A5s A4s A3s A2s AKo KK KQs KJs KTs K9s K8s K7s K6s AQo KQo QQ QJs QTs Q9s Q8s AJo KJo QJo JJ JTs J9s J8s ATo KTo JTo TT T9s T8s 99 98s 88 87s 77 66 55 44 33 22",
        "mixed": "Q8s J8s JTo 87s 33 22",
    },
    "MP": {
        "raise": "AA AKs AQs AJs ATs A9s A8s A7s A6s A5s A4s A3s A2s AKo KK KQs KJs KTs K9s K8s K7s K6s K5s AQo KQo QQ QJs QTs Q9s Q8s AJo KJo QJo JJ JTs J9s J8s ATo KTo QTo JTo TT T9s T8s A9o 99 98s 97s 88 87s 77 76s 66 55 44 33 22",
        "mixed": "QTo 76s",
    },
    "HJ": {
        "raise": "AA AKs AQs AJs ATs A9s A8s A7s A6s A5s A4s A3s A2s AKo KK KQs KJs KTs K9s K8s K7s K6s K5s K4s AQo KQo QQ QJs QTs Q9s Q8s Q7s AJo KJo QJo JJ JTs J9s J8s J7s ATo KTo QTo JTo TT T9s T8s T7s A9o K9o 99 98s 97s A8o 88 87s 86s 77 76s 66 65s 55 44 33 22",
        "mixed": "86s",
    },
    "CO": {
        "raise": "AA AKs AQs AJs ATs A9s A8s A7s A6s A5s A4s A3s A2s AKo KK KQs KJs KTs K9s K8s K7s K6s K5s K4s K3s K2s AQo KQo QQ QJs QTs Q9s Q8s Q7s Q6s Q5s Q4s AJo KJo QJo JJ JTs J9s J8s J7s J6s ATo KTo QTo JTo TT T9s T8s T7s T6s A9o K9o Q9o J9o T9o 99 98s 97s A8o K8o 88 87s 86s A7o 77 76s A6o 66 65s A5o 55 54s 44 33 22",
    },
    "BTN": {
        "raise": "AA AKs AQs AJs ATs A9s A8s A7s A6s A5s A4s A3s A2s AKo KK KQs KJs KTs K9s K8s K7s K6s K5s K4s K3s K2s AQo KQo QQ QJs QTs Q9s Q8s Q7s Q6s Q5s Q4s Q3s Q2s AJo KJo QJo JJ JTs J9s J8s J7s J6s J5s J4s J3s ATo KTo QTo JTo TT T9s T8s T7s T6s T5s T4s A9o K9o Q9o J9o T9o 99 98s 97s 96s 95s A8o K8o Q8o J8o T8o 98o 88 87s 86s 85s A7o K7o J7o 77 76s 75s A6o K6o 66 65s 64s A5o K5o 55 54s A4o 44 A3o 33 A2o 22",
        "mixed": "J7o K5o",
    },
    "SB": {
        "raise": "AA AKs AQs AJs ATs A9s A8s A7s A6s A5s A4s A3s A2s AKo KK KQs KJs KTs K9s K8s K7s K6s K5s K4s K3s K2s KQo QQ QJs QTs Q9s Q8s Q7s Q6s Q5s KJo QJo JJ JTs J9s J8s J7s J6s J5s J4s ATo KTo QTo JTo TT T9s T8s T7s T6s T5s T4s A9o K9o Q9o J9o T9o 99 98s 97s 95s 94s A8o K8o Q8o J8o T8o 98o 88 87s 85s 84s 83s 82s A7o K7o Q7o J7o T7o 97o 87o 77 75s 72s A6o K6o Q6o J6o T6o 96o A5o K5o Q5o J5o A4o",
        "limp": "AKo KK K2s AQo KQo Q5s Q4s Q3s Q2s AJo KJo QJo JJ JTs J5s J4s J3s J2s ATo KTo QTo JTo TT T9s T8s T7s T3s T2s A9o K9o Q9o J9o T9o 99 98s 97s 96s 95s 94s 93s 92s A8o K8o Q8o J8o T8o 98o 88 87s 86s 85s 84s 82s A7o K7o Q7o J7o T7o 87o 77 76s 75s 74s 73s 72s A6o K6o Q6o J6o T6o 96o 86o 76o 66 65s 64s 63s 62s A5o K5o Q5o J5o T5o 95o 85o 75o 65o 55 54s 53s 52s A4o K4o Q4o J4o T4o 94o 84o 74o A3o K3o Q3o J3o T3o 93o A2o K2o Q2o J2o T2o 92o",
        "mixed": "AKo KK K2s KQo Q5s KJo QJo JJ JTs J5s J4s ATo KTo QTo JTo TT T9s T8s T7s A9o K9o Q9o J9o T9o 99 98s 97s 95s 94s A8o K8o Q8o J8o T8o 98o 88 87s 85s 84s 82s A7o K7o Q7o J7o T7o 87o 77 75s 72s A6o K6o Q6o J6o T6o 96o A5o K5o Q5o J5o A4o 74o 92o",
    },
}

CASH_9MAX_100_SOURCE = {
    "UTG+1": {
        "raise": "AA AKs AQs AJs ATs A9s A8s A7s A6s A5s A4s AKo KK KQs KJs KTs K9s K5s AQo KQo QQ QJs QTs AJo JJ JTs TT 99 88 77",
        "mixed": "A7s A6s K9s K5s KQo AJo 77",
    },
    "MP": {
        "raise": "AA AKs AQs AJs ATs A9s A8s A7s A6s A5s A4s A3s AKo KK KQs KJs KTs K9s K5s AQo KQo QQ QJs QTs AJo KJo JJ JTs TT T9s 99 88 77 76s 66",
        "mixed": "A3s K5s KJo 77 76s 66",
    },
    "LJ": {
        "raise": "AA AKs AQs AJs ATs A9s A8s A7s A6s A5s A4s A3s AKo KK KQs KJs KTs K9s K8s K6s K5s AQo KQo QQ QJs QTs Q9s AJo KJo JJ JTs J9s ATo TT T9s 99 88 77 76s 66",
        "mixed": "K6s K5s Q9s KJo J9s ATo 76s 66",
    },
    "HJ": {
        "raise": "AA AKs AQs AJs ATs A9s A8s A7s A6s A5s A4s A3s A2s AKo KK KQs KJs KTs K9s K8s K7s K6s K5s AQo KQo QQ QJs QTs Q9s AJo KJo QJo JJ JTs J9s ATo KTo QTo TT T9s T8s 99 88 77 76s 66 55 54s",
        "mixed": "K5s KTo QTo T8s 76s 55 54s",
    },
    "CO": {
        "raise": "AA AKs AQs AJs ATs A9s A8s A7s A6s A5s A4s A3s A2s AKo KK KQs KJs KTs K9s K8s K7s K6s K5s K4s AQo KQo QQ QJs QTs Q9s Q8s Q7s Q6s AJo KJo QJo JJ JTs J9s J8s ATo KTo QTo JTo TT T9s T8s A9o 99 98s 97s 88 87s 77 76s 66 55 54s 44 33",
        "mixed": "Q7s Q6s 97s 87s 76s 54s 44 33",
    },
    "BTN": {
        "raise": "AA AKs AQs AJs ATs A9s A8s A7s A6s A5s A4s A3s A2s AKo KK KQs KJs KTs K9s K8s K7s K6s K5s K4s K3s K2s AQo KQo QQ QJs QTs Q9s Q8s Q7s Q6s Q5s Q4s Q3s AJo KJo QJo JJ JTs J9s J8s J7s J6s J5s ATo KTo QTo JTo TT T9s T8s T7s T6s A9o K9o Q9o J9o T9o 99 98s 97s 96s A8o K8o T8o 88 87s 86s A7o 77 76s 75s A6o 66 65s A5o 55 54s A4o 44 33 22",
        "mixed": "K8o T8o 75s",
    },
    "SB": {
        "raise": "AA AKs AQs AJs ATs A9s A8s A7s A6s A5s A4s A3s A2s AKo KK KQs KJs KTs K9s K8s K7s K6s K5s K4s K3s K2s AQo KQo QQ QJs QTs Q9s Q8s Q7s Q6s Q5s Q4s Q3s Q2s AJo KJo QJo JJ JTs J9s J8s J7s J6s J5s J4s J3s ATo KTo QTo JTo TT T9s T8s T7s T6s T5s A9o K9o Q9o J9o T9o 99 98s 97s 96s A8o K8o Q8o J8o T8o 98o 88 87s 86s 85s A7o K7o 77 76s 75s A6o 66 65s 64s A5o 55 54s 53s A4o 44 33 22",
        "mixed": "Q8o J8o A3o",
    },
}

CASH_6MAX_100_SOURCE = {
    "UTG": {
        "raise": "AA AKs AQs AJs ATs A9s A8s A7s A6s A5s A4s A3s AKo KK KQs KJs KTs K9s K8s K5s AQo KQo QQ QJs QTs Q9s AJo KJo QJo JJ JTs J9s ATo KTo TT T9s 99 88 77 66",
        "mixed": "K8s K5s QJo J9s KTo 66",
    },
    "MP": {
        "raise": "AA AKs AQs AJs ATs A9s A8s A7s A6s A5s A4s A3s A2s AKo KK KQs KJs KTs K9s K8s K7s K6s K5s AQo KQo QQ QJs QTs Q9s Q8s AJo KJo QJo JJ JTs J9s ATo KTo QTo JTo TT T9s T8s A9o 99 98s 88 87s 77 76s 66 65s 55 54s",
        "mixed": "K5s Q8s QTo JTo T8s A9o 98s 87s 76s 65s 55 54s",
    },
    "CO": {
        "raise": "AA AKs AQs AJs ATs A9s A8s A7s A6s A5s A4s A3s A2s AKo KK KQs KJs KTs K9s K8s K7s K6s K5s K4s K3s AQo KQo QQ QJs QTs Q9s Q8s Q7s Q6s AJo KJo QJo JJ JTs J9s J8s J7s ATo KTo QTo JTo TT T9s T8s T7s A9o 99 98s 97s A8o 88 87s 77 76s 66 65s A5o 55 54s 44 33 22",
        "mixed": "K3s J7s T7s A8o 76s 65s A5o 54s 33 22",
    },
    "BTN": {
        "raise": "AA AKs AQs AJs ATs A9s A8s A7s A6s A5s A4s A3s A2s AKo KK KQs KJs KTs K9s K8s K7s K6s K5s K4s K3s K2s AQo KQo QQ QJs QTs Q9s Q8s Q7s Q6s Q5s Q4s Q3s AJo KJo QJo JJ JTs J9s J8s J7s J6s J5s J4s ATo KTo QTo JTo TT T9s T8s T7s T6s A9o K9o Q9o J9o T9o 99 98s 97s 96s A8o K8o J8o T8o 98o 88 87s 86s A7o 77 76s 75s A6o 66 65s A5o 55 54s A4o 44 33 22",
        "mixed": "J4s K8o J8o T8o 98o",
    },
    "SB": {
        "raise": "AA AKs AQs AJs ATs A9s A8s A7s A6s A5s A4s A3s A2s AKo KK KQs KJs KTs K9s K8s K7s K6s K5s K4s K3s K2s AQo KQo QQ QJs QTs Q9s Q8s Q7s Q6s Q5s Q4s Q3s Q2s AJo KJo QJo JJ JTs J9s J8s J7s J6s J5s J4s ATo KTo QTo JTo TT T9s T8s T7s T6s A9o K9o Q9o J9o T9o 99 97s 96s A8o K8o J8o T8o 98o 88 87s 86s 85s A7o K7o 87o 77 76s 75s 74s A6o 66 65s 64s A5o 55 54s 53s A4o 44 33 22",
        "limp": "AA A7s A6s A5s A4s A3s A2s AKo KK K9s K8s K7s K6s K5s K4s K3s K2s AQo KQo QQ Q9s Q8s Q7s Q6s Q5s Q4s Q3s Q2s AJo KJo QJo JJ J9s J8s J7s J6s J4s J3s J2s ATo KTo QTo JTo TT T9s T8s T7s T5s T4s T3s A9o K9o Q9o J9o T9o 99 98s 97s 96s 95s 94s A8o K8o Q8o J8o T8o 98o 88 87s 86s 85s 84s K7o Q7o J7o T7o 97o 87o 77 76s 75s 74s A6o K6o Q6o 76o 66 65s 63s A5o K5o 55 54s 53s A4o 44 43s A3o 33 A2o 22",
        "mixed": "AA A7s A6s A5s A4s A3s A2s AKo KK K9s K8s K7s K6s K5s K4s K3s K2s AQo KQo QQ Q9s Q8s Q7s Q6s Q5s Q4s Q3s Q2s AJo KJo QJo JJ J9s J8s J7s J6s J4s ATo KTo QTo JTo TT T9s T8s T7s A9o K9o Q9o J9o T9o 99 97s 96s 94s A8o K8o J8o T8o 98o 88 87s 86s 85s 84s K7o Q7o J7o T7o 87o 77 76s 75s 74s A6o Q6o 76o 66 65s 63s A5o 55 54s 53s A4o 44 43s 33 22",
    },
}
