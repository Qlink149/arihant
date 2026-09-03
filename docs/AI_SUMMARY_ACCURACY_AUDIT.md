# AI Summary Accuracy Audit (#45)

**Date:** 2026-09-04 03:07 India Standard Time
**DB (read-only):** `arihant_crm`
**LLM:** provider=`groq` model=`openai/gpt-oss-120b` keys_configured=`2`
**Writes to prod:** none (live regen in-process only)

## Method

1. Sample long-timeline production leads (incl. tracker example phones when present).
2. Rebuild transcript + CRM hints with current `build_masked_transcript` / `build_crm_hints`.
3. Call `generate_lead_insights` live with current `GROUNDING_SYSTEM` prompt.
4. Score fresh persona/moves against status, lost_reason, budget, and newest notes.
5. Keep stored August (or earlier) summaries only for stale-vs-fresh comparison.

## Summary

| Verdict | Count |
|---------|------:|
| PASS | 14 |
| WEAK | 1 |
| FAIL | 0 |
| ERROR | 0 |

**Sample size:** 15

## Per-lead results

### 1. ***0599 — PASS (n=8, status=`Contacted`)

- **Project / budget / lost_reason:** 'ECR - Reserve 16' / 'Under 1Cr' / None
- **Stored AI generated:** none; stale vs latest note days: None
- **Issues:** —
- **Fresh moves:** ['Send a concise WhatsApp message with flexible site‑visit options', 'Attempt a call during alternate hours (e.g., early evening) and leave a clear voicemail', 'Log the outcome of the next contact attempt and set a follow‑up reminder for 3 days later if no response']

**Latest notes:**

- `[note] 2026-02-01T07:39:05` Explained and shared the project details, follow up for site visit
- `[call] 2026-08-26T11:42:07` call forwarded to voice mail
- `[note] 2026-08-27T06:21:31` line was busy. I will try again later.
- `[updated] 2026-08-27T07:54:49` Updated: contacted_at_dt, lead_status, meta_qualified, sla_activated_at_dt, sla_paused, temperature
- `[task_completed] 2026-09-02T08:02:29` Task completed: Follow up — log outcome for this lead

**Stored summary (head):**

> (empty)

**Fresh summary (current prompt):**

The lead is currently interested in the ECR – Reserve 16 project with a budget under 1 Cr, though they have not specified a configuration or possession timeline. Early in February they were responsive, requesting details and indicating they needed time to arrange a site visit, but they never confirmed a date. Since late August, attempts to reach them by phone have gone to voicemail or encountered a busy line, and the latest note simply says the rep will try again later, indicating a low level of current engagement. The lead remains in the 'Contacted' stage with a pending site‑visit request and no pricing or booking actions taken. The rep should verify whether the buyer is still interested and, if so, secure a concrete site‑visit slot, as the earlier enthusiasm has not translated into action.

### 2. ***6576 — PASS (n=23, status=`RNR`)

- **Project / budget / lost_reason:** 'OMR - Vivriti' / '1-2 Cr' / None
- **Stored AI generated:** 2026-08-17 05:24:07.668000; stale vs latest note days: 11
- **Issues:** —
- **Fresh moves:** ['Send a courteous ‘pause acknowledgment’ message now', 'Log a pre‑call checklist for the Jan\u202f2027 follow‑up', 'Set a tentative site‑visit window for early 2027']

**Latest notes:**

- `[transfer] 2026-08-27T06:29:46` Transferred from Anusha Omprakash to jigar
- `[call] 2026-08-27T07:15:06` Client is RNR.
- `[call] 2026-08-28T09:49:11` Spoke to the client he said that currently he is not persuing a property purchase due to personale reasons. He said that he would resume his hunt again
- `[note] 2026-08-28T09:49:45` in 5 Months.
- `[task] 2026-08-28T10:02:04` Task: Call Back in 5 Months Time. | Due: 2027-01-01 at 10:50 | Priority: medium | Assigned to: jigar

**Stored summary (head):**

> The buyer, Pradeep, is currently interested in the OMR - Vivriti project with a budget of 1-2 Cr. Initially, he had shown interest in Fully Integrated Plots at Pattipulam, ECR, with a budget range of 50-60 Lakhs, but his preferences seem to

**Fresh summary (current prompt):**

Pradeep is currently listed for the OMR – Vivriti project with a budget of 1‑2 Cr. Earlier he showed interest in site visits and even scheduled a visit after a busy weekend, but in the latest call (28 Aug) he disclosed personal reasons for pausing his property hunt and asked to be contacted again in about five months. Since then he has been ringing‑no‑response (RNR) and the lead status reflects that pause. His engagement shifted from active (WhatsApp replies, site‑visit intent) to a temporary hold, so the rep should treat him as a warm lead on hold rather than a hot prospect. The next conversation should gently reconfirm his timeline, verify that his budget and project preference (Vivriti) remain unchanged, and re‑ignite interest with fresh Vivriti collateral when the 5‑month window arrives.

### 3. ***7720 — PASS (n=73, status=`Unqualified`)

- **Project / budget / lost_reason:** 'ECR - Reserve 16;Saligramam Melange' / 'Under 1Cr' / 'Not interested'
- **Stored AI generated:** 2026-08-07 06:53:14.801000; stale vs latest note days: 25
- **Issues:** —
- **Fresh moves:** ['Update lead status to Lost – Not Interested and record lost reason', 'Send a courteous closure message thanking the buyer and offering future assistance', 'Create a follow‑up reminder for 6 months later to check if interest resurfaces']

**Latest notes:**

- `[note] 2026-08-31T09:00:16` no response
- `[call] 2026-09-01T11:52:29` disconnecting the call
- `[updated] 2026-09-02T06:33:17` Updated: lead_status, lost_reason
- `[call] 2026-09-02T06:34:43` client informed, he not enquired any properties and not interested
- `[transfer] 2026-09-02T06:38:08` Transferred from Anantharaman to jigar. Notes: not interested

**Stored summary (head):**

> The buyer is currently interested in projects ECR - Reserve 16 and Saligramam Melange, with a budget under 1Cr. The engagement style has been mostly unresponsive, with multiple instances of RNR and declined calls. However, there was a note 

**Fresh summary (current prompt):**

The buyer was initially curious about two projects – ECR Reserve 16 and Saligramam Melange – and had a budget under 1 Cr, but over the past two months has become completely unresponsive, declining calls, turning on disappearing WhatsApp messages, and repeatedly not answering. The latest interaction on 2026-09-02 confirms the buyer explicitly stated he has not inquired about any properties and is not interested. This moves the lead firmly into an Unqualified / Lost stage with no active intent or configuration preference to verify. The rep should treat the lead as closed, but note the prior interest in both projects in case the prospect re‑engages later.

### 4. ***3907 — WEAK (n=66, status=`Unqualified`)

- **Project / budget / lost_reason:** 'Saligramam Melange' / 'Under 1Cr' / 'Ringing no response'
- **Stored AI generated:** 2026-08-14 06:47:09.389000; stale vs latest note days: 15
- **Issues:** lost_reason_or_not_interested_not_reflected
- **Fresh moves:** ['Verify and obtain a valid contact method', 'Send a concise email summarizing Saligramam Melange details and request preferred contact', 'Schedule a follow‑up reminder in 2 weeks to check for any change in availability or interest', "If no response after the email and follow‑up, mark the lead as lost with reason 'No response / invalid contact'"]

**Latest notes:**

- `[note] 2026-08-26T07:16:44` RNR , Message sent
- `[note] 2026-08-27T06:34:34` RNR , Message sent
- `[note] 2026-08-28T09:45:19` Number not in use
- `[note] 2026-08-29T09:23:55` Number not in use
- `[updated] 2026-08-29T09:24:02` Updated: lead_status, lost_reason, temperature

**Stored summary (head):**

> The buyer is currently interested in the Saligramam Melange project with a budget under 1Cr. They have been unresponsive to multiple follow-up calls and WhatsApp messages, with the latest notes indicating that messages have been sent but no

**Fresh summary (current prompt):**

The prospect is currently positioned as an Unqualified lead interested in the Saligramam Melange project with a budget under 1 Cr. He resides in the UAE and has indicated that a brother‑in‑law will visit the site, but he has not provided a direct contact number and the existing number appears to be inactive. Over the past month, every call has resulted in RNR and WhatsApp messages have been viewed but not replied to, indicating a disengaged or unreachable stance. The CRM notes flag the number as 'not in use', reinforcing the need to verify contact details before any further sales effort. A productive next conversation would require a fresh, reliable communication channel and a clear confirmation of his intent to proceed.

### 5. ***7808 — PASS (n=60, status=`Unqualified`)

- **Project / budget / lost_reason:** 'ECR - Reserve 16' / '2-5 Cr' / 'Ringing no response'
- **Stored AI generated:** 2026-08-16 08:53:51.460000; stale vs latest note days: 15
- **Issues:** —
- **Fresh moves:** ['Send a brief, value‑focused WhatsApp message asking for a preferred contact time', 'If no reply within 48\u202fhours, email a summary of the Reserve 16 offering with a clear call‑to‑action', 'Schedule a final outreach call from a senior manager, noting the lead’s pattern of declining calls']

**Latest notes:**

- `[note] 2026-08-30T05:47:46` no response
- `[note] 2026-08-30T05:48:28` no response
- `[transfer] 2026-08-30T07:25:50` Transferred from Anantharaman to Anusha Omprakash. Notes: no response
- `[note] 2026-08-31T10:31:30` Ringing and disconnecting.
- `[updated] 2026-08-31T10:31:42` Updated: lead_status, lost_reason

**Stored summary (head):**

> The buyer is currently interested in the ECR - Reserve 16 project with a budget of 2-5 Cr. The buyer has been unresponsive to calls, with a history of RNR and declined calls. Despite this, the buyer had previously engaged with the sales tea

**Fresh summary (current prompt):**

The lead is currently listed for the ECR – Reserve 16 project with a budget band of 2‑5 Cr, but has shown virtually no engagement in the past two months. Their communication style is highly unresponsive – calls are repeatedly declined, ringing with no answer, and WhatsApp messages receive no reply. The lead remains in an Unqualified stage; no site visit, brochure, or pricing discussion has progressed beyond the initial request in January. There are no recent indications of a change in budget or configuration, but the persistent lack of response suggests the buyer may have lost interest or is unavailable, which the rep should verify. A productive next conversation would aim to confirm whether the prospect is still considering a purchase and, if so, secure a definitive time slot or preferred contact channel.

### 6. ***0747 — PASS (n=73, status=`Closed Lost`)

- **Project / budget / lost_reason:** 'OMR - Vivriti;Saligramam Melange' / '2-5 Cr' / 'Not interested'
- **Stored AI generated:** 2026-08-15 10:08:05.537000; stale vs latest note days: 18
- **Issues:** —
- **Fresh moves:** ['Send a courteous closure and feedback request', 'Log loss reason and set a nurture reminder for 3‑4 months', 'Confirm no immediate alternative project interest']

**Latest notes:**

- `[call] 2026-08-29T12:17:31` Client is RNR.
- `[call] 2026-08-30T06:24:53` Client is RNR.
- `[call] 2026-08-31T09:44:00` Voicemail.
- `[call] 2026-09-03T08:34:06` Client has updated that the vastu has been rejected and she is not persuing a purchase currently. She was out of time so she could not revert. Hence moving to lost.
- `[updated] 2026-09-03T08:34:27` Updated: lead_status, lost_reason

**Stored summary (head):**

> The buyer is currently interested in OMR - Vivriti and Saligramam Melange projects, with a budget of 2-5 Cr. She has visited the site with her son and is keen on checking the vastu of the property. She has requested a cost sheet, which has 

**Fresh summary (current prompt):**

The buyer, Lakshmi, was evaluating two Arihant projects – a 1800 sq ft unit in Saligramam Melange and Unit 1A in OMR‑Vivriti – with a budget in the 2‑5 Cr range. She engaged primarily via WhatsApp, responded politely when contacted, and even visited the Vivriti site on 15 Aug 2026, after which a cost sheet was shared. Post‑visit, she requested a Vastu review and promised to revert within three days. On 3 Sep 2026 she communicated that the Vastu assessment was negative and she is not pursuing a purchase, leading to the lead being marked Closed Lost. The interaction pattern shows many periods of Ring‑No‑Response, but the decisive recent update overrides earlier enthusiasm. The rep should verify that the Vastu rejection is final and note the loss reason for future reference.

### 7. ***4784 — PASS (n=41, status=`Closed Lost`)

- **Project / budget / lost_reason:** 'ECR - Reserve 16' / '1-2 Cr' / 'Budget'
- **Stored AI generated:** 2026-08-12 05:25:03.614000; stale vs latest note days: None
- **Issues:** —
- **Fresh moves:** ['Confirm interest in alternative projects (e.g., Melange) within ₹2\u202fCr', 'Send a curated shortlist of north‑facing units in Melange that fit a ₹2\u202fCr budget (including 2\u202fBHK or 3\u202fBHK with 2 toilets options)', 'Schedule a brief follow‑up call (15\u202fmin) to discuss family feedback and any flexibility on configuration', 'If no interest is confirmed, send a courteous closure email summarizing the discussion and offering future assistance']

**Latest notes:**

- `[site_visit] 2026-08-10T07:51:25` Requirement 3bhk,3 toilet, available units shown, budget concern will discuss with family and revert
- `[updated] 2026-08-11T08:55:06` Updated: lead_status, next_action_date, sv_followup_1_entered_at_dt
- `[whatsapp] 2026-08-11T08:56:42` requirement 3bhk,3toilet, budget 2crores only but we try to convince them for 3bhk, 2toilet client will discuss and update
- `[updated] 2026-08-12T05:24:11` Updated: is_rnr, lead_status, lost_reason
- `[whatsapp] 2026-08-12T05:25:01` Site visit completed, requirements 3bhk,3toilet, budget only 2crores not able to stretch the budget so dropped

**Stored summary (head):**

> The buyer is currently interested in project ECR - Reserve 16, with a budget of 1-2 Cr and a requirement for a 3BHK, 3-toilet configuration. They had a site visit and were shown available units, but expressed budget concerns and were unable

**Fresh summary (current prompt):**

The buyer is a Saligramam resident who visited the Reserve 16 site on 9‑10 Aug and confirmed a requirement for a 3 BHK unit with 3 toilets. Their budget caps at Rs2 Cr and they explicitly stated they cannot stretch beyond this, leading to the decision to drop Reserve 16. During the call on 8 Aug they expressed dissatisfaction with Reserve 16 and said they would check the Melange project for a north‑facing option. Since the site visit, communication has been minimal, with the lead now marked Closed Lost. The rep should verify whether the buyer is still open to alternative projects like Melange within the Rs2 Cr budget, possibly with a reduced configuration, before formally closing the loop.

### 8. ***1006 — PASS (n=41, status=`Closed Lost`)

- **Project / budget / lost_reason:** 'Saligramam Melange' / '1-2 Cr' / 'Not interested'
- **Stored AI generated:** 2026-08-01 09:11:53.395000; stale vs latest note days: 2
- **Issues:** —
- **Fresh moves:** ['Send a courteous acknowledgment and keep the door open', 'Update CRM with the explicit lost reason and set a future check‑in reminder (e.g., 3‑4\u202fmonths later)', 'Ask if she would like to be added to a newsletter or notified about upcoming projects in the same price band']

**Latest notes:**

- `[note] 2026-04-24T05:16:45` Spoken and basic details given . she is from Chrompet - she will go through the details and get connected later . Sent details over WA
- `[updated] 2026-08-01T09:11:02` Updated: lead_status, next_action_date, sla_activated_at_dt, sla_paused, sv_followup_1_entered_at_dt, temperature
- `[note] 2026-08-01T09:11:52` Clients phone is in Ringing But No Response
- `[updated] 2026-08-03T10:45:27` Updated: lead_status, lost_reason
- `[whatsapp] 2026-08-03T10:45:46` [9:50 pm, 2/8/2026] Kavitha V - Buyer Melange: Very sorry for not responding, we were in a great confusion thatswhy. We have decided to put my niece in private medical college so we r not able to proceed with ur project.

**Stored summary (head):**

> The client is a woman from Chrompet who has been in touch with the sales team regarding a potential purchase. She has been busy and has had to reschedule visits to the site multiple times, but has shown interest in the project. She has ment

**Fresh summary (current prompt):**

The buyer was targeting the Saligramam Melange project with a budget of 1‑2 Cr. Over the past months she was highly engaged on WhatsApp—responding politely, scheduling a site visit, requesting the cost sheet and availability, and reviewing materials. Despite completing the site visit and receiving pricing details, she recently informed us (2 Aug 2026) that due to a family decision to fund her niece’s private medical college, she cannot proceed with any purchase at this time. The lead is now marked Closed Lost, indicating the funnel has stalled at the decision stage. The rep should acknowledge her situation, keep the relationship warm for potential future needs, and verify if there’s any interest in alternative projects or a later follow‑up.

### 9. ***3777 — PASS (n=87, status=`RNR`)

- **Project / budget / lost_reason:** 'Saligramam Melange' / '1-2 Cr' / None
- **Stored AI generated:** 2026-08-14 05:00:29.207000; stale vs latest note days: 20
- **Issues:** —
- **Fresh moves:** ['Send a concise WhatsApp message asking for preferred contact time and confirming interest', 'Call the client using the alternative number they previously answered and ask if they prefer email or SMS', 'Escalate to senior sales manager if no response within 48\u202fhours of the WhatsApp outreach']

**Latest notes:**

- `[call] 2026-08-30T07:47:54` Client is RNR.
- `[call] 2026-08-31T08:00:26` Client is RNR.
- `[call] 2026-09-01T10:45:30` Spoke to the client he said that he will try and visit today. He will reconfirm.
- `[call] 2026-09-03T06:18:41` Client did not visit. Today he has declined my call.
- `[call] 2026-09-03T11:52:25` Client is RNR.

**Stored summary (head):**

> The buyer is currently interested in the Saligramam Melange project with a budget of 1-2 Cr. The lead status is RNR, indicating that the buyer has not been responding to calls. Despite multiple follow-up calls and reminders, there has been 

**Fresh summary (current prompt):**

The buyer is currently looking at the Saligramam Melange project with a budget in the 1‑2 Cr range. Early in July they expressed intent to visit the site over a weekend and were coordinating with our PropMart colleague Goutham, indicating a moderate level of interest. However, since mid‑July the lead has gone silent, repeatedly marked as Ringing No Response (RNR) despite multiple call and WhatsApp attempts, and most recent notes (Sept 1‑3) show they missed a planned visit and declined calls. The lead’s status remains RNR, and there is no updated configuration, possession timeline, or explicit purchase intent, so the rep should verify whether the buyer is still interested or has shifted priorities. A good next conversation would re‑establish contact, confirm the preferred communication channel, and clarify if the Saligramam Melange still meets their needs.

### 10. ***3051 — PASS (n=50, status=`RNR`)

- **Project / budget / lost_reason:** 'Saligramam Melange' / 'Under 1Cr' / None
- **Stored AI generated:** 2026-08-17 05:46:29.095000; stale vs latest note days: 1
- **Issues:** —
- **Fresh moves:** ['Reach out via alternative channel (SMS/email) to confirm network issue and interest', 'Send a concise price snapshot for the 1584\u202fsq\u202fft unit with a clear call‑to‑action for a preferred callback time', 'Log a follow‑up task for 3\u202fbusiness days later to check response and, if still silent, schedule a 5‑day‑later outreach before marking as dormant']

**Latest notes:**

- `[note] 2026-08-14T09:56:22` RNR
- `[note] 2026-08-17T05:46:27` RNR , Message sent
- `[transfer] 2026-08-18T09:24:38` Transferred from Gowtham j to jigar. Notes: RNR for long time
- `[call] 2026-08-18T12:07:06` Client Out of Network Coverage Area.
- `[transfer] 2026-08-18T12:07:28` Transferred from jigar to Narendran S. Notes: Client is RNR for me anusha and Gowtham

**Stored summary (head):**

> The buyer is currently interested in the Saligramam Melange project with a budget under 1Cr. They had a site visit scheduled and were shared price details of a 1584 sq.ft. unit, but have since been unresponsive, with multiple 'RNR' notes an

**Fresh summary (current prompt):**

The buyer is currently looking at Saligramam Melange with a budget under 1 Cr and had asked for pricing on a 1584 sq ft unit. Over the past two months they have been consistently unreachable – calls are declined, messages go unanswered, and the latest note flags them as being out of network coverage. Their engagement style is non‑responsive and they have not confirmed any site‑visit or next‑step, effectively stalling the funnel at the early interest stage. The rep should verify whether the network issue is temporary and reconfirm if the project remains a viable option for them. A good next conversation would re‑establish contact, briefly restate the price details, and lock in a specific time for a call or meeting.

### 11. ***2882 — PASS (n=48, status=`RNR`)

- **Project / budget / lost_reason:** 'Saligramam Melange' / 'Under 1Cr' / None
- **Stored AI generated:** 2026-08-09 05:41:15.093000; stale vs latest note days: 24
- **Issues:** —
- **Fresh moves:** ['Send an empathetic health‑check message', 'Share the latest Melange brochure and pricing, ask for budget/configuration updates', 'Ask for her preferred communication channel and best time to talk', 'Set a 7‑day follow‑up reminder; if still no response, move to nurture campaign']

**Latest notes:**

- `[note] 2026-08-19T10:20:04` Cut the while speaking
- `[note] 2026-08-20T11:19:50` RNR
- `[note] 2026-08-25T07:06:57` RNR
- `[note] 2026-08-26T10:31:56` RNR
- `[note] 2026-09-02T09:15:49` RNR

**Stored summary (head):**

> The buyer is currently interested in the Saligramam Melange project with a budget under 1Cr. The buyer has been unresponsive to calls and messages, with a history of declining calls and not replying to messages. However, the buyer has been 

**Fresh summary (current prompt):**

The buyer is currently interested in the Saligramam Melange project with a budget under 1 Cr and has not specified a configuration or possession timeline. She initially engaged on WhatsApp, requested the brochure and even scheduled a callback for 10:30 AM, indicating warm interest at that time. Since early June 2026 she has mentioned being unwell, has only replied that she will get in touch if she has plans, and consistently reads messages without responding, leading to a prolonged RNR status. The key unknowns are her health status and whether she still intends to purchase, as well as any possible changes to budget or timeline that need verification. A productive next conversation would be a brief, empathetic health check‑in, confirming her preferred contact method and timing, and offering any updated project details.

### 12. ***0457 — PASS (n=72, status=`Nurturing`)

- **Project / budget / lost_reason:** 'Saligramam Melange' / '1-2 Cr' / None
- **Stored AI generated:** 2026-08-08 05:22:30.977000; stale vs latest note days: 26
- **Issues:** —
- **Fresh moves:** ['Send a personalized WhatsApp message acknowledging the missed connections and asking for a convenient time to talk', 'Schedule a brief phone call (5‑10\u202fmin) at the agreed time or, if no reply, attempt a call during early evening hours two days after the WhatsApp outreach', 'If still no response, email the latest Saligramam Melange brochure with a short note offering a virtual tour link and a request for feedback', 'Create a follow‑up task for Malathy to check back in 10\u202fdays if all attempts remain unanswered, marking the lead as ‘potentially cold’ pending response']

**Latest notes:**

- `[note] 2026-08-29T09:38:28` RNR , Message sent
- `[note] 2026-08-31T10:18:37` RNR , Message sent
- `[note] 2026-09-01T11:28:44` Message sent
- `[note] 2026-09-02T07:13:18` RNR , Message sent
- `[transfer] 2026-09-03T12:01:23` Transferred from Gowtham j to Malathy. Notes: RNR for long time

**Stored summary (head):**

> The buyer is currently interested in the Saligramam Melange project with a budget under 1Cr. They have been engaged in conversation, with recent notes indicating they need time till June mid and then asked to be called back. The buyer has a

**Fresh summary (current prompt):**

The buyer is currently looking at the Saligramam Melange project with a budget in the 1‑2 Cr range; configuration details have not been provided. Over the past several months they have been polite but increasingly unresponsive, with numerous Ring‑No‑Response (RNR) entries and only occasional WhatsApp messages. The lead was originally at the Site‑Visit Scheduled stage, but repeated health issues, a son’s interview, and a request for a mid‑June follow‑up have pushed the timeline out, and the buyer has not confirmed any visit since early May. The CRM still marks the lead as Warm and in Nurturing, but the long string of RNRs suggests the prospect may be drifting cold and should be re‑qualified. A good next conversation would re‑establish contact, confirm whether the budget and project interest remain, and secure a concrete next step (call, virtual tour, or site visit).

### 13. ***0000 — PASS (n=53, status=`Nurturing`)

- **Project / budget / lost_reason:** 'ECR - Reserve 16' / 'Under 1Cr' / None
- **Stored AI generated:** 2026-08-16 09:29:36.358000; stale vs latest note days: 17
- **Issues:** —
- **Fresh moves:** ['Send a concise WhatsApp check‑in', 'Email a tailored project snapshot with limited‑time incentive', 'Schedule a follow‑up call for the next available slot', 'Update CRM with latest engagement status and set a 2‑week nurture task']

**Latest notes:**

- `[whatsapp] 2026-08-28T11:06:37` I have sent a follow up message to the client.
- `[call] 2026-08-29T11:22:14` Client is RNR.
- `[whatsapp] 2026-08-30T09:22:24` I have sent a message to the client.
- `[whatsapp] 2026-09-01T12:02:23` I have sent a message to the client.
- `[call] 2026-09-03T07:36:54` Client has declined my call.

**Stored summary (head):**

> The buyer is currently interested in the ECR - Reserve 16 project with a budget under 1Cr. They have been engaged in a series of conversations, initially expressing flexibility in plot size and a budget of Rs50 lakhs–1 crore. However, recent

**Fresh summary (current prompt):**

The buyer is currently being nurtured for the ECR – Reserve 16 project with a budget under 1 Cr and a flexible plot size. Over the past months they have been largely unresponsive, repeatedly marking calls as RNR or declining them, and only sporadically replying to WhatsApp messages. The last concrete signal was on 18 Aug, when they said they would get back in two days after a friend’s plot offer, but no follow‑up has been received since. This places them firmly in the early nurturing stage – no brochure request, pricing sent, or site‑visit confirmed. A key contradiction to verify is whether the friend’s opportunity has materialised and if the buyer still has any intent to pursue a plot with Arihant.

### 14. ***5163 — PASS (n=40, status=`Nurturing`)

- **Project / budget / lost_reason:** 'ECR - Reserve 16' / '1-2 Cr' / None
- **Stored AI generated:** 2026-08-08 04:53:56.128000; stale vs latest note days: 26
- **Issues:** —
- **Fresh moves:** ['Personalized WhatsApp check‑in', 'Send digital project kit', 'Set follow‑up reminder for 10 days later', 'Confirm any budget or configuration updates']

**Latest notes:**

- `[call] 2026-09-01T11:53:20` no response
- `[note] 2026-09-02T05:48:57` no response
- `[transfer] 2026-09-02T07:16:00` Transferred from Anantharaman to jigar. Notes: no response
- `[call] 2026-09-03T07:36:01` Client is RNR.
- `[call] 2026-09-03T08:54:00` Client called back and said that her husband is in madurai so she travells back and forth she will confirm only once she is free.

**Stored summary (head):**

> The buyer is currently interested in the ECR - Reserve 16 project with a budget of 1-2 Cr. They have been engaged in conversation, with a history of requesting details and discussing site visits, although recent attempts at contact have bee

**Fresh summary (current prompt):**

The buyer is currently eyeing the ECR – Reserve 16 project with a stated budget of 1‑2 Cr. She has been warm historically, requesting details and showing willingness to visit the site, but over the past month she has become largely unresponsive, with multiple RNR attempts. The latest interaction (09‑03) reveals she travels frequently because her husband is in Madurai and will only confirm interest when she has a free window. She remains a nurturing‑stage lead, but her engagement has dropped to passive, and the next conversation must focus on securing a concrete time slot or alternative virtual engagement while respecting her travel constraints.

### 15. ***6578 — PASS (n=58, status=`Visit Completed`)

- **Project / budget / lost_reason:** 'ECR - Reserve 16' / '2-5 Cr' / None
- **Stored AI generated:** 2026-08-06 05:46:54.160000; stale vs latest note days: 21
- **Issues:** —
- **Fresh moves:** ['Lock in Friday meeting details', 'Send comprehensive financial and documentation packet', 'Confirm registration name(s) and prepare forms', 'Post‑meeting follow‑up to collect advance and finalize booking']

**Latest notes:**

- `[whatsapp] 2026-08-22T10:05:55` Yes mam what to process loan and basic document details
Will decide which name tomorrow only as my wife and son name may be will take
Want to construct early process etc
 1234 detailed dimension etc
- `[whatsapp] 2026-08-22T10:06:56` He replied due to meeting extended. he will connect later
- `[whatsapp] 2026-08-24T06:05:45` He replied that he is very much keen in going ahead with the booking. he wanted to clarify
Pls share the following 

Advance amount minimal 
And 30 days amount 
And bank loan of 30 laks 
And construction process 
Any oth
- `[call] 2026-08-24T06:07:12` Spoke to him and gave him update on the required information. Also shared him the final price.
- `[whatsapp] 2026-08-27T06:50:55` I am back again Chennai tomorrow night will do Friday

**Stored summary (head):**

> The buyer is currently interested in project ECR - Reserve 16, with a budget of 2-5 Cr. They have shown interest in plot no. 118 and have asked to block it. The buyer has been engaged in conversations, discussing loan possibilities, best pr

**Fresh summary (current prompt):**

The buyer is a retirement‑focused client looking for a ~1200 sq ft corner plot (Plot 118) in ECR‑Reserve 16, with a budget of 2‑5 Cr. He has visited the site, blocked the plot and repeatedly expressed strong intent to book, but his schedule is erratic due to travel and other commitments. Over the past weeks he has asked for the minimal advance amount, a 30‑day payment schedule, loan feasibility for ~30 L, construction timelines, registration details and the full project layout. The latest WhatsApp note (2026‑08‑27) indicates he will be back in Chennai tomorrow night and plans to meet on Friday, signalling a concrete window to close. The rep should verify the exact advance amount, confirm the name(s) for registration, and lock in the Friday meeting to move from intent to booking.

## Themes

- 13/15 stored summaries were older than the latest timeline activity — cached AI is not a valid accuracy test without live regen.
- Current prompt + live regen often reflects newest notes better than stored mid-August text.

## Recommendation for tracker #45

**Verdict:** Done with notes (live audit)

Treat #45 as **Done with notes**: current prompt + `openai/gpt-oss-120b` is materially better than stale August cache on terminal/lost leads. Residual: FAIL=0, WEAK=1. Prod UI still shows cached summaries until regen — consider regen-on-status-change.

## Safety

- This script never `$set`s AI fields on production.
- Phones masked as `***` + last 4 digits.
