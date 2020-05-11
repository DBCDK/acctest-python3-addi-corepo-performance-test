
def buildNode = 'nightly-itwn-001.dbc.dk'
//def buildNode = 'regression-itwn-001'
def TEST_DURATION_IN_SECONDS=900
def COREPO_IMAGE='isworker/corepo-fbs-test-no-relations-snapshot-postgres-1.0:20181109'
THREAD_POOL=4


def ownerEmail = "os-team@dbc.dk"
def ownerSlack = "search"

pipeline {
    agent {
        docker {
            image 'docker.dbc.dk/dbc-debian-python3:latest'
            args '-u 0:0 -v /var/run/docker.sock:/var/run/docker.sock'
            alwaysPull true
            label buildNode
        }
    }

    environment {
        UID = sh(script: 'stat -c %U .', returnStdout: true).trim()
        GID = sh(script: 'stat -c %G .', returnStdout: true).trim()
    }

    options {
        disableConcurrentBuilds()
        buildDiscarder(logRotator(artifactDaysToKeepStr: '', artifactNumToKeepStr: '', daysToKeepStr: '30', numToKeepStr: '30'))
        timestamps()
    }

    triggers {
        cron('H 2 * * *')
    }

    stages {
        stage('Docker-Enable') {
            steps {
                script {
                    sh '''
                        # Add 'docker' group to jenkins user
                        groupadd -r -o -g $(stat -c %g /var/run/docker.sock) docker
                        gpasswd -a $UID docker
                    '''
                }
            }
        }

        stage('Root') {
            steps {
                script {
                    sh '''
                        whoami
                        export DEBIAN_FRONTEND=noninteractive
                        apt-get update
                        apt-get --yes install --no-install-recommends default-jdk python3-os-dbc python3-os-perftest-dbc
                    '''
                }
            }
        }

        stage('Su') {
            steps {
                script {
                    // If root has made any files - fix ownership
                    sh ''' chown --recursive $UID:$GID . '''
                    su(env.UID)
                }
            }
        }

        stage('Run Addi Corepo Performance test') {
            steps {
                copyArtifacts filter: "addi-metrics.json", fingerprintArtifacts: true, projectName: JOB_NAME
                script {
                    sh """#!/bin/bash -x
                        # Needs a USER name in environment for docker names
                        export USER=TEST

                        python3 run_perf_test.py $JOB_NAME $BUILD_NUMBER $COREPO_IMAGE -t $THREAD_POOL -r $TEST_DURATION_IN_SECONDS
                    """
                }
            }
        }


    }
    post {
        always {
            archiveArtifacts artifacts: 'run_perf_test.log, addi-metrics.json, logs.zip'
            publishHTML reportDir: "performance-report", reportFiles: 'index.html', reportName: "Performance Report", keepAll: true, alwaysLinkToLastBuild: false, allowMissing: true
            publishHTML reportDir: "performance-report-auto", reportFiles: 'index.html', reportName: "Performance Report Automatically generated", keepAll: true, alwaysLinkToLastBuild: false, allowMissing: true
            sh '''#!/bin/bash -x
                rm -fr logfiles
            '''
        }
        failure {
            script {
                emailext(
                        recipientProviders: [developers(), culprits()],
                        to: "${ownerEmail}",
                        subject: "[Jenkins] ${env.JOB_NAME} #${env.BUILD_NUMBER} failed",
                        mimeType: 'text/html; charset=UTF-8',
                        body: "<p>The master build failed. Log attached. </p><p><a href=\"${env.BUILD_URL}\">Build information</a>.</p>",
                        attachLog: true)
                slackSend(channel: "${ownerSlack}",
                        color: 'warning',
                        message: "${env.JOB_NAME} #${env.BUILD_NUMBER} failed and needs attention: ${env.BUILD_URL}",
                        tokenCredentialId: 'slack-global-integration-token')
            }
        }
    }
}

// Uses global property: _SU_CLOSURE_
// In post { ... } use steps.sh
def sh(obj) {
    if (! (obj instanceof Map) )
        obj = [ script: obj ]
    def closure = { m -> steps.sh(m) }
    try {
        closure = _SU_CLOSURE_
    } catch(Exception e) {
        // _SU_CLOSURE_ hasn't been set yet
    }
    return closure.call(obj)
}

// Now hashbang notation will fail if it is not bourne-shell compliant - i.e. no #!/usr/bin/python
def su(uid = null) {
    if (uid == null || uid == 'root') {
        _SU_CLOSURE_ = { m -> steps.sh(m) }
    } else {
        _SU_CLOSURE_ = { m ->
            // If root rerun script as user
            try {
                // check for hashbang notation
                def matcher = m['script'] =~ /(?ms)(#!(\S+)[^\n]*\n)(.*)/
                if (matcher.matches()) {
                    m['script'] = matcher.group(1) + '''set +x; if [ $(id -u) = 0 ]; then set +x ; exec /usr/bin/su ''' + uid + ''' -c "''' + matcher.group(2) + ''' -e '$(echo -n "$0" | sed "s/'/'\\''/g")'"; fi; set -x; ''' + matcher.group(3)
                } else {
                    m['script'] = '''set +x; if [ $(id -u) = 0 ]; then set +x ; exec /usr/bin/su ''' + uid + ''' -c "/bin/sh -e '$(echo -n "$0" | sed "s/'/'\\''/g")'"; fi; set -x; ''' + m['script']
                }
            } catch (Exception e) {
            }
            steps.sh(m)
        }
    }
}
