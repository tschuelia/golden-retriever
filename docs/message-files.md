# Message files and RTF

## Why a message can have three bodies

MAPI messages can expose plain text, HTML, and rich text through three related
properties:

| Representation | MAPI property                    | Typical purpose     |
| -------------- | -------------------------------- | ------------------- |
| Plain text     | `PidTagBody` (`0x1000`)          | Universal fallback  |
| Rich text      | `PidTagRtfCompressed` (`0x1009`) | Compressed RTF body |
| HTML           | `PidTagHtml` (`0x1013`)          | Direct HTML bytes   |

Source: Microsoft
[Creating Message Text](https://learn.microsoft.com/en-us/office/client-developer/outlook/mapi/creating-message-text)
and
[Formatted Text in MAPI](https://learn.microsoft.com/en-us/office/client-developer/outlook/mapi/formatted-text-in-mapi).

The representations are alternatives, not three independent messages. MAPI
clients and stores can generate one from another and use synchronization
metadata to decide which is authoritative. Therefore, if `PidTagHtml` is present
and trustworthy for the application, no RTF de-encapsulation may be needed.

## What RTF-encapsulated HTML solves

Plain RTF cannot retain every HTML construct exactly. Converting HTML to RTF
would otherwise lose comments, insignificant whitespace, unknown tags, and
markup with no RTF equivalent. Microsoft therefore defined an RTF document that
serves two readers:

1. a normal RTF reader sees a formatted approximation; and
2. a de-encapsulating reader reconstructs the original HTML fragments.

This format is described by MS-OXRTFEX. Its product notes document it across
legacy Exchange and Outlook generations; they also note that Exchange 2013,
2016, and 2019 do not emit this form. That history is why parsers still encounter
the format in stored mail even though not every modern producer creates it.

Source: MS-OXRTFEX §2.1 and
[Appendix A notes `<1>`–`<12>`](https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-oxrtfex/de024708-40c7-46fd-bffc-16cd04f89817).

## Where it sits in an `.msg` file

An Outlook `.msg` file is a Compound File Binary container. Variable-length
properties are stored in substg streams. `PidTagRtfCompressed` is property ID
`0x1009` with binary type `0x0102`, so its conventional message-level stream is:

```text
__substg1.0_10090102
```

The stream contains an RTF compression wrapper, not immediately parseable RTF.
Its header includes compressed and uncompressed sizes, a magic value selecting
compressed or uncompressed storage, and a CRC. The payload must first be decoded
according to MS-OXRTFCP.

Sources: MS-OXMSG §2.2.3
[Variable Length Properties](https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-oxmsg/08185828-e9e9-4ef2-bcd2-f6e69c00891b),
[PidTagRtfCompressed](https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-oxprops/ce0b22a1-ba51-454b-85d7-45bf7bb68a18),
and MS-OXRTFCP §2.1.3.1
[RTF Compression Header](https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-oxrtfcp/a1f226ed-31e3-4565-9d26-af3c6714c93f).

## End-to-end retrieval

```text
Outlook .msg compound file
        |
        | locate property 0x1009 / stream __substg1.0_10090102
        v
PidTagRtfCompressed bytes
        |
        | validate header and decompress according to MS-OXRTFCP
        v
uncompressed RTF bytes
        |
        | golden_retriever.deencapsulate(...)
        v
Python str containing HTML or plain text
        |
        | optionally normalize charset; always apply caller security policy
        v
serialized or rendered content
```

Only the third step belongs to this library. Keeping the boundaries separate is
useful: compound-file parsing has storage and size hazards, decompression has CRC
and dictionary rules, and de-encapsulation has RTF state and encoding rules.

## Attachments and `cid:` URLs

The extracted HTML can retain references such as `cid:image001.png@...`.
MS-OXRTFEX §2.2.3.4 describes integrating attachments, but that requires the
containing message and attachment properties. golden-retriever never sees those
objects, so it leaves references untouched. A caller can match Content-ID values
using properties such as
[PidTagAttachContentId](https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-oxprops/9643fc31-3d26-45c0-b639-b08969fcd267).
