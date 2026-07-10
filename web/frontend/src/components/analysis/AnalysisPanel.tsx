import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useAnalysisStore } from '../../stores/analysisStore'

const SECTION_TITLES: Record<string, string> = {
  market_report: 'Market Analysis',
  sentiment_report: 'Social Sentiment',
  news_report: 'News Analysis',
  fundamentals_report: 'Fundamentals Analysis',
  investment_plan: 'Research Team Decision',
  trader_investment_plan: 'Trading Team Plan',
  final_trade_decision: 'Portfolio Management Decision',
}

const SECTION_ORDER = [
  'market_report',
  'sentiment_report',
  'news_report',
  'fundamentals_report',
  'investment_plan',
  'trader_investment_plan',
  'final_trade_decision',
]

export default function AnalysisPanel() {
  const reportSections = useAnalysisStore((s) => s.reportSections)

  const availableSections = SECTION_ORDER.filter((key) => reportSections[key])

  const latestSection = availableSections.length > 0
    ? availableSections[availableSections.length - 1]
    : null

  const latestContent = latestSection ? reportSections[latestSection] : null

  return (
    <div className="flex flex-col overflow-hidden">
      <div className="p-4 border-b border-border-subtle">
        <h3 className="text-sm font-semibold text-text-faint uppercase tracking-wider">
          Analysis Report
        </h3>
      </div>

      <div className="flex-1 overflow-auto p-6">
        {latestContent ? (
          <div>
            {latestSection && (
              <h4 className="text-lg font-semibold text-accent mb-4" style={{ fontFamily: 'var(--font-serif)' }}>
                {SECTION_TITLES[latestSection] || latestSection}
              </h4>
            )}
            <div className="prose prose-themed prose-sm max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {latestContent}
              </ReactMarkdown>
            </div>
          </div>
        ) : (
          <div className="text-text-faint text-center py-16">
            <p>Waiting for analysis report...</p>
            <p className="text-xs mt-2">Reports will appear as agents complete their work</p>
          </div>
        )}

        {availableSections.length > 1 && (
          <div className="mt-8 pt-6 border-t border-border-subtle">
            <h4 className="text-sm font-semibold text-text-faint mb-4 uppercase tracking-wider">
              All Reports
            </h4>
            <div className="space-y-6">
              {availableSections.filter((k) => k !== latestSection).map((key) => (
                <div key={key}>
                  <h5 className="text-md font-semibold text-accent-2 mb-2" style={{ fontFamily: 'var(--font-serif)' }}>
                    {SECTION_TITLES[key] || key}
                  </h5>
                  <div className="prose prose-themed prose-sm max-w-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {reportSections[key]}
                    </ReactMarkdown>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
