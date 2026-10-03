# Vigil

Always-on medical device complaint agent, running 100% locally on the Dell Pro Max with GB10
(NemoClaw + OpenClaw + OpenShell, local model, Telegram).

Built at the Dell x NVIDIA AI Hackathon, Boston, 3 October 2026.

## The problem
Medical device makers must report deaths, serious injuries and dangerous malfunctions to the FDA
within 30 days (5 days when urgent action is needed; 10 days for hospitals) under 21 CFR 803.
Complaints pile up unread. Philips Respironics had over 222,000 foam/particle complaints in its own
files before the June 2021 CPAP recall, while the FDA's public database showed almost nothing.

## What Vigil does
1. Code layer (every complaint, instant): priority score from red-flag words, event type,
   distress score; completeness and duplicate checks; spike detection per device.
   Signals only raise priority, never lower it.
2. AI check (every complaint): reportable / not reportable / needs info, legal reason, deadline.
3. Agent (reportable or unsure): starts the clock, drafts the report narrative, alerts the team
   on Telegram, writes trend alerts.
4. Human approves every decision. Nothing is silently dropped; every decision is logged.

## Why local
Complaints contain patient health information (HIPAA) and the company's quality data.
Nothing leaves the box.

## Data
Public FDA data via openFDA (MAUDE device reports, recalls, enforcement, classification).

## Setup
_To be written on the day._
