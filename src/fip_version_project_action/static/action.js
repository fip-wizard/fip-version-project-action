const action = new dsw.Action()

jQuery(document).ready(function() {
    let $loader = jQuery('#loader')
    let $content = jQuery('#content')
    let $error = jQuery('#error')

    $loader.show()
    $content.hide()
    $error.hide()

    action
        .init()
        .then((data) => {
            console.log('Action initialized with data:', data)

            jQuery('#btn-close').on('click', function() {
                action.sendResult(false, 'FIP version action has been closed by the user after encountering an error.')
            })
            jQuery('#btn-cancel').on('click', function() {
                action.sendResult(false, 'FIP version action has been closed by the user.')
            })
            jQuery('#btn-confirm').on('click', function() {
                jQuery(this).prop('disabled', true)
                jQuery('#btn-cancel').prop('disabled', true)
                // extract version
                const versionMajor = jQuery('#version-major').val()
                const versionMinor = jQuery('#version-minor').val()
                const versionPatch = jQuery('#version-patch').val()
                const version = `${versionMajor}.${versionMinor}.${versionPatch}`
                const description = jQuery('#version-description').val()

                console.log('User confirmed with version:', version)
                // send ajax
                jQuery.ajax({
                    url: `${ROOT_PATH}/api/submit-version`,
                    method: 'POST',
                    data: JSON.stringify({
                        projectUuid: data.projectUuid,
                        userToken: data.userToken,
                        version: version,
                        description: description,
                    }),
                    contentType: 'application/json',
                    success: function(response) {
                        console.log('Action executed successfully:', response)
                        action.sendResult(true, `FIP version action completed successfully and updated version to **${version}**.`)
                    },
                    error: function(xhr, status, error) {
                        console.error('Error executing action:', error)
                        jQuery('#error-message').text('Failed to execute action. Please try again later.')
                        $(this).prop('disabled', false)
                        $error.show()
                    }
                })
            })
            jQuery('.version-part').on('change', function() {
                const major = jQuery('#version-major').val()
                const minor = jQuery('#version-minor').val()
                const patch = jQuery('#version-patch').val()
                const lastSubmittedVersion = jQuery('#latest-version').text()
                const nextVersion = `${major}.${minor}.${patch}`
                const parsedLast = parseSemver(lastSubmittedVersion)
                const parsedNext = parseSemver(nextVersion)
                // check if next version is higher than the submitted
                if (parsedLast) {
                    if (compareSemver(parsedNext, parsedLast) <= 0) {
                        jQuery('#warning').show()
                        jQuery('#btn-confirm').prop('disabled', true)
                    } else {
                        jQuery('#warning').hide()
                        jQuery('#btn-confirm').prop('disabled', false)
                    }
                }
            })
            jQuery('.suggestion').on('click', function(event) {
                event.preventDefault()
                const suggestedVersion = jQuery(this).text()
                const parts = suggestedVersion.split('.')
                jQuery('#version-major').val(parts[0])
                jQuery('#version-minor').val(parts[1])
                jQuery('#version-patch').val(parts[2])
            })

            jQuery.ajax({
                url: `${ROOT_PATH}/api/prepare-action`,
                method: 'POST',
                data: JSON.stringify({
                    projectUuid: data.projectUuid,
                    userToken: data.userToken,
                }),
                contentType: 'application/json',
                success: function(response) {
                    console.log('Received versions:', response)

                    if (response.ok) {
                        $loader.hide()
                        $content.show()
                        const latestSubmitted = computeLatest(response.submittedVersions)
                        const latestVersion = latestSubmitted || '(no valid submitted yet)'
                        const projectVersion = response.questionnaireVersion || '(not set)'
                        jQuery('#latest-version').text(latestVersion)
                        jQuery('#current-version').text(projectVersion)
                        const workingVersion = response.questionnaireVersion
                        // form fields and suggestions
                        let formMajor = 0
                        let formMinor = 1
                        let formPatch = 0
                        let suggestMajor = '1.0.0'
                        let suggestMinor = '0.1.0'
                        let suggestPatch = '0.0.1'
                        if (workingVersion) {
                            const parsed = parseSemver(workingVersion)
                            if (parsed) {
                                formMajor = parsed[0]
                                formMinor = parsed[1]
                                formPatch = parsed[2]
                                suggestMajor = `${formMajor + 1}.0.0`
                                suggestMinor = `${formMajor}.${formMinor + 1}.0`
                                suggestPatch = `${formMajor}.${formMinor}.${formPatch + 1}`
                            }
                        }
                        jQuery('#version-major').val(formMajor)
                        jQuery('#version-minor').val(formMinor)
                        jQuery('#version-patch').val(formPatch)
                        jQuery('#suggest-major').text(suggestMajor)
                        jQuery('#suggest-minor').text(suggestMinor)
                        jQuery('#suggest-patch').text(suggestPatch)
                    } else {
                        jQuery('#error-message').text('Failed to load versions: ' + response.message)
                        $loader.hide()
                        $error.show()
                    }
                },
                error: function(xhr, status, error) {
                    console.error('Error fetching versions:', error)
                    jQuery('#error-message').text('Failed to load versions. Please try again later.')
                    $loader.hide()
                    $error.show()
                }
            })
        })
        .catch(error => {
            console.error(error)
        })
})

function parseSemver(v) {
    const match = v.match(/^(\d+)\.(\d+)\.(\d+)$/);
    if (!match) return null;
    return match.slice(1).map(Number);
}

function compareSemver(a, b) {
    for (let i = 0; i < 3; i++) {
        if (a[i] > b[i]) return 1;
        if (a[i] < b[i]) return -1;
    }
    return 0;
}

function computeLatest(versions) {
    let best = null;
    for (const item of versions) {
      const parsed = parseSemver(item.version);
      if (!parsed) continue;

      if (!best || compareSemver(parsed, best) > 0) {
         best = parsed;
      }
    }
    return best ? best.join(".") : null;
}
