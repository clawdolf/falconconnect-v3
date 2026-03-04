import { useState } from 'react'

const BASE_URL = window.location.origin
const CALENDAR_TOKEN = '8a7e8401aa785ad8e9d3459e4c675a9e'

const FEEDS = [
  {
    name: 'Appointments',
    description: '15-min events with 60-min and 24-hour reminders + Notion links',
    path: `/api/calendar/appointments.ics?token=${CALENDAR_TOKEN}`,
  },
  {
    name: 'Follow-Ups',
    description: 'All-day events with 8am morning reminder + Notion links',
    path: `/api/calendar/followups.ics?token=${CALENDAR_TOKEN}`,
  },
]

function CalendarLinks() {
  const [copied, setCopied] = useState(null)

  const copyToClipboard = (url, idx) => {
    navigator.clipboard.writeText(url).then(() => {
      setCopied(idx)
      setTimeout(() => setCopied(null), 2000)
    })
  }

  return (
    <section className="section">
      <h2 className="section-title">Calendar Subscriptions</h2>
      <p className="section-desc">
        Subscribe to these URLs in Apple Calendar or any iCal client.
        They auto-refresh with the latest data from Notion.
      </p>
      <div className="feed-list">
        {FEEDS.map((feed, idx) => {
          const url = `${BASE_URL}${feed.path}`
          return (
            <div key={idx} className="feed-item">
              <div className="feed-header">
                <span className="feed-name">{feed.name}</span>
                <span className="feed-desc">{feed.description}</span>
              </div>
              <div className="feed-url-row">
                <code className="feed-url-code">{url}</code>
                <button
                  className="btn btn-sm"
                  onClick={() => copyToClipboard(url, idx)}
                >
                  {copied === idx ? 'Copied' : 'Copy'}
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}

export default CalendarLinks
