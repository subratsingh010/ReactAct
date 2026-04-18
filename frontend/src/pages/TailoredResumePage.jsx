import ResumeBuilderPage from './ResumeBuilderPage'

function TailoredResumePage() {
  return (
    <ResumeBuilderPage
      pageTitle="Tailored Resume Builder"
      subtitle="Tailor resume content for each JD while keeping the same format."
      importSessionKey="tailoredBuilderImport"
      resumeIdSessionKey="tailoredBuilderResumeId"
      showJdBox
      jdSessionKey="tailoredBuilderJdText"
      enableTailorFlow
      minimalTailorUi
      referenceBuilderSessionKey="tailoredBuilderReferenceBuilder"
      referenceResumeIdSessionKey="tailoredBuilderReferenceResumeId"
      aiModelSessionKey="tailoredBuilderAiModel"
      tailorModeSessionKey="tailoredBuilderTailorMode"
      showSaveButton
      disableAutoLoadDefaultResume
    />
  )
}

export default TailoredResumePage
