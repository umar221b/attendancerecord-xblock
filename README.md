# Installation

Install the Xblock into your OpenEdx Instance, then add it to a course in the Advanced Module List in Advanced Settings (add `"attendancerecord"`).

# Studio Setup Examples

The module supports up to 3 levels of nesting. The last level will contain the IDs and names of the sessions. The ID of a session can be any string, but it must be unique. Options also have a unique ID and a name each. The first option is the default option. Make sure you include a "not recorded" option.


```json
{
    "nesting": 1,
    "sessions": [
        ["sun", "Sunday"],
        ["mon", "Monday"],
        ["wed", "Wednesday"]
    ],
    "options": [
        ["not-recorded", "Not recorded"],
        ["attended", "attended"],
        ["absent", "absent"]
    ]
}
```

```json
{
    "nesting": 2,
    "sessions": {
        "Week 1": [
            ["week1-sun", "Sunday"],
            ["week2-mon", "Monday"],
        ],
        "Week 2": [
            ["week2-sun", "Sunday"],
            ["week2-wed", "Wednesday"]
        ],
    },
    "options": [
        ["not-recorded", "Not recorded"],
        ["attended", "attended"],
        ["late", "late"],
        ["absent", "absent"]
    ]
}
```

```json
{
    "nesting": 3,
    "sessions": {
        "Week 1": {
            "Sunday": [
                ["week1-sun-morning", "Morning Session"], 
                ["week1-sun-evening", "Evening Session"]
            ],
            "Monday": [
                ["week1-mon-morning", "Morning Session"],
                ["week1-mon-evening", "Evening Session"]
            ]
        },
        "Week 2": {
            "Sunday": [
                ["week2-sun-morning", "Morning Session"],
                ["week2-sun-afternoon", "Afternoon Session"]
            ],
            "Wednesday": [
                ["week2-wed-afternoon", "Afternoon Session"],
                ["week2-wed-evening", "Evening Session"]
            ]
        }
    },
    "options": [
        ["not-recorded", "Not recorded"],
        ["attended", "attended"],
        ["late", "late"],
        ["absent", "absent"]
    ]
}
```

# Support
Future work should make creating sessions more user-friendly, right now it works by specifiying a JSON object.
