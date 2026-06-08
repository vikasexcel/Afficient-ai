# Aifficient — User Guide

**Version:** Phase 5C | **Audience:** Sales Teams, Campaign Managers

---

## 1. Getting Started

### Logging In

1. Navigate to `https://app.your-domain.com`
2. Enter your email and password
3. Click **Sign In**

If you don't have an account, ask your admin to invite you via the Members page.

---

## 2. Lead Management

### Creating a Lead List

Lead lists are collections of prospects you want to contact in a campaign.

1. Go to **Leads** in the left navigation
2. Click **New List**
3. Enter a name (e.g., "Q3 SaaS Prospects")
4. Click **Create**

### Adding Leads

**Individual lead:**
1. Open your lead list
2. Click **Add Lead**
3. Fill in: First Name, Last Name, Phone (required), Email, Company, Job Title
4. Click **Save**

**CSV import:**
1. Prepare a CSV with columns: `first_name`, `last_name`, `phone`, `email`, `company`, `job_title`
2. In the lead list, click **Import CSV**
3. Select your file and confirm the column mapping
4. Click **Import**

### Lead Statuses

| Status | Meaning |
|--------|---------|
| `new` | Just added, not yet contacted |
| `in_progress` | Currently in an active campaign |
| `qualified` | AI determined lead is a good fit |
| `meeting_booked` | Meeting scheduled |
| `opted_out` | Lead requested no contact |
| `do_not_call` | DNC list; will never be dialled |

---

## 3. Campaign Wizard

### Creating a Campaign

1. Go to **Campaigns** → click **New Campaign**
2. Enter a campaign name
3. Select a **Lead List**
4. Select a **Playbook** (workflow template)
5. Configure the launch schedule:
   - **Start Immediately** — activates now
   - **Scheduled** — pick a date, time, and timezone
6. Configure business hours (calls only placed within these hours)
7. (Optional) Set a retry policy
8. Click **Launch** or **Save as Draft**

### Campaign Statuses

| Status | Meaning |
|--------|---------|
| `draft` | Not launched; can be edited |
| `scheduled` | Will activate at the configured time |
| `active` | Currently dialling leads |
| `paused` | Paused by user; can be resumed |
| `completed` | All leads processed |
| `cancelled` | Manually cancelled |

### Retry Configuration

Set how many times the system retries a lead after a failed call:

- **Max Attempts**: 1–10 (default: 5)
- **Retry Interval**: Minutes between retries (default: 15)
- **Backoff Strategy**: Fixed (same interval each time) or Exponential (doubles each attempt)
- **Retry On**: Choose which outcomes trigger a retry (e.g., `no_answer`, `busy`)

---

## 4. Workflow Builder (Playbooks)

Playbooks define the sequence of actions taken for each lead.

### Node Types

| Node | Description |
|------|-------------|
| **EMAIL** | Send a personalised email to the lead |
| **CALL** | Place an AI-powered outbound call |
| **WAIT** | Pause for a configured number of hours before the next step |
| **LINKEDIN_CONNECTION** | Send a LinkedIn connection request |
| **LINKEDIN_MESSAGE** | Send a LinkedIn direct message |
| **CONDITION** | Branch based on a field value (e.g., email opened → go to CALL; not opened → go to WAIT) |
| **STOP** | End the workflow for this lead |

### Building a Workflow

1. Go to **Playbooks** → click **New Playbook**
2. Give it a name and description
3. Drag nodes from the left panel onto the canvas
4. Connect nodes by dragging from the output handle of one node to the input of the next
5. Click a node to configure its properties:
   - **EMAIL**: Subject line, body (supports `{{first_name}}`, `{{company}}` placeholders)
   - **CALL**: Call script for the AI agent
   - **WAIT**: Duration in hours
   - **CONDITION**: Field, operator, value
6. Click **Save**

### Variable Placeholders

Use `{{ }}` syntax in email subjects, bodies, and call scripts:

| Placeholder | Value |
|-------------|-------|
| `{{first_name}}` | Lead's first name |
| `{{last_name}}` | Lead's last name |
| `{{company}}` | Lead's company |
| `{{job_title}}` | Lead's job title |
| `{{email}}` | Lead's email address |
| `{{phone}}` | Lead's phone number |

### Example Workflows

**Simple outreach:**
```
EMAIL → WAIT (24h) → CALL → STOP
```

**Multi-touch with qualification:**
```
LINKEDIN_CONNECTION → WAIT (48h) → EMAIL → CONDITION
    ├─ [opened]   → CALL
    └─ [not opened] → WAIT (72h) → EMAIL → STOP
```

---

## 5. Campaign Monitoring

### Monitor Dashboard

1. Go to **Campaigns** → select a campaign → click **Monitor**
2. See real-time execution status:
   - **Total Executions**: Leads processed so far
   - **Completed**: Successfully finished
   - **In Progress**: Currently running
   - **Queued**: Waiting to be processed
   - **Failed**: Encountered an error
   - **Retrying**: Scheduled for a retry attempt

### Execution Detail

Click any execution row to see:
- Lead information
- Current workflow node
- Call outcome (if applicable)
- Retry history
- Failure reason (if failed)

---

## 6. Analytics Dashboard

### Navigating Analytics

Go to **Analytics** in the left navigation. Use the tabs to switch between:

| Tab | What it shows |
|-----|---------------|
| **Overview** | Campaign counts, execution rates, lead funnel |
| **Campaigns** | Campaign status breakdown, execution rates |
| **Email** | Emails sent, failed, success rate, daily trend |
| **Calls** | Calls attempted, completed, voicemail count, connect rate |
| **LinkedIn** | Connection requests, messages, daily trend |
| **Funnel** | Lead progression from Upload → Meeting Booked |
| **Workflow** | Most-used workflows, node type distribution |

### Date Range

Use the **7d / 30d / 90d** selector to change the reporting window.

### Exporting Data

Click the **Export** dropdown to export the current tab's data as:
- **CSV** — opens in Excel / Google Sheets
- **JSON** — raw data for integration
- **PDF** — browser print dialog

---

## 7. Transcripts

After an AI call is completed and finalised, the transcript is available in **Transcripts**:

1. Go to **Transcripts**
2. Find the call by date or lead name
3. Click the row to see:
   - Full conversation transcript (AI + lead)
   - Qualification status (BANT: Budget / Authority / Need / Timeline)
   - Call summary
   - Total tokens and call duration
4. Click **Export JSON** to download the full transcript

---

## 8. Settings

### Profile

Go to **Settings** → **Profile** to update:
- Full name
- Email address
- Password

### Organisation

(OWNER/ADMIN only) Go to **Settings** → **Organisation** to update:
- Organisation name

### Members

(OWNER/ADMIN only) Go to **Settings** → **Members** to:
- Invite new users by email
- Change user roles
- Remove users

### Appearance

Go to **Settings** → **Appearance** to switch between:
- **Light** / **Dark** / **System** theme

---

## 9. Tips & Best Practices

- **Lead quality over quantity**: Campaigns with fewer, high-intent leads outperform bulk low-quality lists.
- **Personalise email nodes**: Use `{{first_name}}` and `{{company}}` for 3–5x higher reply rates.
- **Set business hours**: Avoid calling leads outside 9am–5pm in their timezone.
- **Use WAIT nodes**: 24–72h delays between touchpoints feel less aggressive.
- **Monitor the first campaign closely**: Use the Monitor dashboard to catch configuration issues early.
- **Review call transcripts**: They reveal what's working in your AI agent's script.
- **Use the Condition node**: Branch based on email opens to call only engaged leads.
