import { useMemo } from 'react'

import { buildResumeViewModel } from '../utils/resumeShared'

export default function ResumeSheet({ form }) {
  const model = useMemo(
    () => buildResumeViewModel(form, { forceEducationScoreWhenValue: false }),
    [form],
  )

  const compactSpacing = true
  const sectionClass = `resume-section${model.sectionUnderline ? ' has-underline' : ''}`
  const hasHtmlContent = (value) => String(value || '').replace(/<[^>]+>/g, '').trim().length > 0
  const getCustomByKey = (key) => {
    if (!key.startsWith(model.customKeyPrefix)) return null
    const id = key.slice(model.customKeyPrefix.length)
    return model.customSections.find((section) => section.id === id) || null
  }

  return (
    <article
      className={`resume-sheet${compactSpacing ? ' is-compact' : ''}`}
      style={{
        '--resume-font-family': model.bodyFontFamily,
        '--resume-font-size': `${Number.isFinite(model.bodyFontSizePt) ? model.bodyFontSizePt : 10}pt`,
        '--resume-line-height': `${Number.isFinite(model.bodyLineHeight) ? model.bodyLineHeight : 1}`,
        '--resume-sheet-padding-top': `${model.topPagePaddingIn}in`,
        '--resume-sheet-padding': `${model.pageMarginIn}in`,
      }}
    >
      <header className={`resume-head${model.sectionUnderline ? ' no-divider' : ''}`}>
        <h2>{model.fullName || 'Your Name'}</h2>
        <p className="resume-head-line">{model.contactLine}</p>
        {model.links.length > 0 && (
          <p className="resume-head-links">
            {model.links.map((item, idx) => (
              <span key={`${item.label}-${item.url}`}>
                {idx > 0 ? ' | ' : ''}
                <a href={item.url} target="_blank" rel="noreferrer">
                  {item.label}
                </a>
              </span>
            ))}
          </p>
        )}
      </header>

      {model.orderedKeys.map((key) => {
        if (key === 'summary') {
          if (!model.summaryEnabled || !hasHtmlContent(model.summaryHtml)) return null
          return (
            <div key="summary" className={sectionClass}>
              <h3>{model.summaryHeading || 'Summary'}</h3>
              <div className="resume-summary" dangerouslySetInnerHTML={{ __html: model.summaryHtml }} />
            </div>
          )
        }

        if (key === 'skills') {
          if (!hasHtmlContent(model.skillsHtml)) return null
          return (
            <div key="skills" className={sectionClass}>
              <h3>Skills</h3>
              <div className="resume-rich" dangerouslySetInnerHTML={{ __html: model.skillsHtml }} />
            </div>
          )
        }

        if (key === 'experience') {
          if (!model.experiences.length) return null
          return (
            <div key="experience" className={sectionClass}>
              <h3>Experience</h3>
              {model.experiences.map((exp, index) => (
                <div key={`exp-prev-${index}`} className="resume-exp">
                  <div className="resume-exp-head">
                    <div className="resume-exp-left">
                      <span className="resume-exp-company">{exp.company}</span>
                      {exp.company && exp.title && <span className="resume-exp-sep"> – </span>}
                      <span className="resume-exp-title">{exp.title}</span>
                    </div>
                    <div className="resume-exp-right">
                      {[exp.startDate, exp.isCurrent ? 'Present' : exp.endDate]
                        .filter(Boolean)
                        .join(' – ')}
                    </div>
                  </div>
                  <div className="resume-exp-body">
                    <div className="resume-rich" dangerouslySetInnerHTML={{ __html: exp.highlights }} />
                  </div>
                </div>
              ))}
            </div>
          )
        }

        if (key === 'projects') {
          if (!model.projects.length) return null
          return (
            <div key="projects" className={sectionClass}>
              <h3>Projects</h3>
              {model.projects.map((proj, index) => (
                <div key={`proj-prev-${index}`} className="resume-exp">
                  <div className="resume-exp-head">
                    <div className="resume-exp-left">
                      <span className="resume-exp-company">{proj.name}</span>
                      {proj.normalizedUrl && (
                        <a
                          className="resume-link resume-project-link"
                          href={proj.normalizedUrl}
                          target="_blank"
                          rel="noreferrer"
                          data-url={proj.normalizedUrl}
                        >
                          link
                        </a>
                      )}
                    </div>
                    <div className="resume-exp-right" />
                  </div>
                  <div className="resume-exp-body">
                    <div className="resume-rich" dangerouslySetInnerHTML={{ __html: proj.highlights }} />
                  </div>
                </div>
              ))}
            </div>
          )
        }

        if (key === 'education') {
          if (!model.educations.length) return null
          return (
            <div key="education" className={sectionClass}>
              <h3>Education</h3>
              {model.educations.map((edu, index) => (
                <div key={`edu-prev-${index}`} className="resume-exp">
                  <div className="resume-exp-head">
                    <div className="resume-exp-left">
                      <div className="resume-edu-inst">
                        <span className="resume-exp-company">{edu.institution}</span>
                      </div>
                      {(edu.program || edu.scoreText) && (
                        <div className="resume-edu-meta">
                          {edu.program && <span className="resume-exp-title">{edu.program}</span>}
                          {edu.program && edu.scoreText && <span className="resume-exp-sep"> | </span>}
                          {edu.scoreText && <span className="resume-exp-title">{edu.scoreText}</span>}
                        </div>
                      )}
                    </div>
                    <div className="resume-exp-right">
                      {[edu.startDate, edu.isCurrent ? 'Present' : edu.endDate]
                        .filter(Boolean)
                        .join(' – ')}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )
        }

        if (key.startsWith(model.customKeyPrefix)) {
          const custom = getCustomByKey(key)
          if (!custom || !hasHtmlContent(custom.content)) return null
          return (
            <div key={key} className={sectionClass}>
              <h3>{custom.title?.trim() || 'Custom section'}</h3>
              <div className="resume-rich" dangerouslySetInnerHTML={{ __html: custom.content }} />
            </div>
          )
        }

        return null
      })}
    </article>
  )
}
