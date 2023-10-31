import pkg_resources
from web_fragments.fragment import Fragment
from xblock.core import XBlock
from xblock.fields import Scope, List, Dict, Integer, String
from xblockutils.resources import ResourceLoader
from xblockutils.settings import XBlockWithSettingsMixin
from xblockutils.publish_event import PublishEventMixin
from xblock.completable import XBlockCompletionMode
from .utils import DummyTranslationService, _
from django import utils
import six
import time
import json

try:
    # pylint: disable=import-error, bad-option-value, ungrouped-imports
    from django.conf import settings
    from api_manager.models import GroupProfile
    HAS_GROUP_PROFILE = True
except ImportError:
    HAS_GROUP_PROFILE = False

class ResourceMixin(XBlockWithSettingsMixin):
    loader = ResourceLoader(__name__)

    @staticmethod
    def resource_string(path):
        """Handy helper for getting resources from our kit."""
        data = pkg_resources.resource_string(__name__, path)
        return data.decode("utf8")

    @property
    def i18n_service(self):
        """ Obtains translation service """
        return self.runtime.service(self, "i18n") or DummyTranslationService()

    def get_translation_content(self):
        try:
            return self.resource_string('public/js/translations/{lang}/textjs.js'.format(
                lang=utils.translation.to_locale(utils.translation.get_language()),
            ))
        except IOError:
            return self.resource_string('public/js/translations/en/textjs.js')

    def create_fragment(self, context, template, css, js, js_init):
        frag = Fragment()
        frag.add_content(self.loader.render_django_template(
            template,
            context=context,
            i18n_service=self.i18n_service
        ))

        frag.add_css(self.resource_string(css))

        frag.add_javascript(self.resource_string(js))
        frag.add_javascript(self.get_translation_content())
        frag.initialize_js(js_init)
        return frag
    
    def _get_block_id(self):
        """
        Returns unique ID of this block. Useful for HTML ID attributes.

        Works both in LMS/Studio and workbench runtimes:
        - In LMS/Studio, use the location.html_id method.
        - In the workbench, use the usage_id.
        """
        if hasattr(self, 'location'):
            return self.location.html_id()  # pylint: disable=no-member

        return six.text_type(self.scope_ids.usage_id)

class CSVExportMixin(object):
    """
    Allows Surveys XBlocks to support CSV downloads of all users'
    details per block.
    """
    active_export_task_id = String(
        # The UUID of the celery AsyncResult for the most recent export,
        # IF we are sill waiting for it to finish
        default="",
        scope=Scope.user_state_summary,
    )
    last_export_result = Dict(
        # The info dict returned by the most recent successful export.
        # If the export failed, it will have an "error" key set.
        default=None,
        scope=Scope.user_state_summary,
    )

    @XBlock.json_handler
    def csv_export(self, data, suffix=''):
        """
        Asynchronously export given data as a CSV file.
        """
        # Launch task
        from .tasks import export_csv_data  # Import here since this is edX LMS specific

        # Make sure we nail down our state before sending off an asynchronous task.
        async_result = export_csv_data.delay(
            six.text_type(getattr(self.scope_ids, 'usage_id', None)),
            six.text_type(getattr(self.runtime, 'course_id', 'course_id')),
        )
        if not async_result.ready():
            self.active_export_task_id = async_result.id
        else:
            self._store_export_result(async_result)

        return self._get_export_status()

    @XBlock.json_handler
    def get_export_status(self, data, suffix=''):
        """
        Return current export's pending status, previous result,
        and the download URL.
        """
        return self._get_export_status()

    def _get_export_status(self):
        self.check_pending_export()
        return {
            'export_pending': bool(self.active_export_task_id),
            'last_export_result': self.last_export_result,
            'download_url': self.download_url_for_last_report,
        }

    def check_pending_export(self):
        """
        If we're waiting for an export, see if it has finished, and if so, get the result.
        """
        from .tasks import export_csv_data  # Import here since this is edX LMS specific
        if self.active_export_task_id:
            async_result = export_csv_data.AsyncResult(self.active_export_task_id)
            if async_result.ready():
                self._store_export_result(async_result)

    @property
    def download_url_for_last_report(self):
        """ Get the URL for the last report, if any """
        from lms.djangoapps.instructor_task.models import ReportStore  # pylint: disable=import-error

        # Unfortunately this is a bit inefficient due to the ReportStore API
        if not self.last_export_result or self.last_export_result['error'] is not None:
            return None

        report_store = ReportStore.from_config(config_name='GRADES_DOWNLOAD')
        course_key = getattr(self.scope_ids.usage_id, 'course_key', None)
        return dict(report_store.links_for(course_key)).get(self.last_export_result['report_filename'])

    def _store_export_result(self, task_result):
        """ Given an AsyncResult or EagerResult, save it. """
        self.active_export_task_id = ''
        if task_result.successful():
            if isinstance(task_result.result, dict) and not task_result.result.get('error'):
                self.last_export_result = task_result.result
            else:
                self.last_export_result = {'error': u'Unexpected result: {}'.format(repr(task_result.result))}
        else:
            self.last_export_result = {'error': six.text_type(task_result.result)}

    def prepare_data(self):
        """
        Return a two-dimensional list containing cells of data ready for CSV export.
        """
        raise NotImplementedError

    def get_filename(self):
        """
        Return a string to be used as the filename for the CSV export.
        """
        raise NotImplementedError

class EnrollmentMixin(object):
    def _get_enrollments(course_id, track=None, cohort=None, active_only=False, excluded_course_roles=None, user_ids=None):
        try:
            from django.apps import apps   # pylint: disable=import-error
            from django.db.models import Exists, OuterRef   # pylint: disable=import-error
        except ModuleNotFoundError:
            return []
        """
        Return iterator of enrollment dictionaries.

        {
            'user_id': user id
            'username': username
            'user_email: email
            'full_name': user's full name
            'enrolled': bool
            'track': enrollment mode
        }
        """
        
        filters = {
            'course_id': course_id
        }
        if user_ids:
            filters['student_id__in'] = user_ids

        enrollments = apps.get_model('student', 'CourseEnrollment').objects.filter(**filters).select_related(
            'user').prefetch_related('programcourseenrollment_set')
        if track:
            enrollments = enrollments.filter(mode=track)
        if cohort:
            enrollments = enrollments.filter(
                user__cohortmembership__course_id=course_id,
                user__cohortmembership__course_user_group__name=cohort)
        if active_only:
            enrollments = enrollments.filter(is_active=True)
        if excluded_course_roles:
            course_access_role_filters = {
                "user": OuterRef('user'),
                "course_id": course_id
            }
            if 'all' not in excluded_course_roles:
                course_access_role_filters['role__in'] = excluded_course_roles
            enrollments = enrollments.annotate(has_excluded_course_role=Exists(
                apps.get_model('student', 'CourseAccessRole').objects.filter(**course_access_role_filters)
            ))
            enrollments = enrollments.exclude(has_excluded_course_role=True)

        for enrollment in enrollments:
            enrollment_dict = {
                'user': enrollment.user,
                'user_id': enrollment.user.id,
                'username': enrollment.user.username,
                'user_email': enrollment.user.email,
                'full_name': enrollment.user.profile.name,
                'enrolled': enrollment.is_active,
                'track': enrollment.mode,
            }

            yield enrollment_dict

    def get_enrollments(self, course_key, track=None, cohort=None, user_ids=[]):
        try:
            from openedx.core.djangoapps.course_groups.cohorts import get_cohort   # pylint: disable=import-error
        except ModuleNotFoundError:
            # TODO: this is for testing
            yield {
                    'user': {},
                    'user_id': 'student_1',
                    'username': 'testuser',
                    'user_email': 'test@user.com',
                    'full_name': 'Test User',
                    'enrolled': True,
                    'track': 'professional',
                }
            return

        """
        Return iterator of user dicts
        """
        enrollments = _get_enrollments(course_key,track=track, cohort=cohort, excluded_course_roles=[], user_ids=user_ids)
        for enrollment in enrollments:
            cohort = get_cohort(enrollment['user'], course_key, assign=False)
            user_info = {
                'user_id': enrollment['user_id'],
                'username': enrollment['username'],
                'user_email': enrollment['email'],
                'full_name': enrollment['full_name'],
                'enrolled': enrollment['enrolled'],
                'track': enrollment['track'],
                'cohort': cohort.name if cohort else None,
            }

            yield user_info


@XBlock.wants('settings')
@XBlock.needs('i18n')
class AttendanceRecordXBlock(XBlock, ResourceMixin, PublishEventMixin, CSVExportMixin, EnrollmentMixin):
    """
    Adds a module for recording attendance
    """
    completion_mode = XBlockCompletionMode.EXCLUDED
    has_author_view = True
    event_namespace = 'xblock.attendancerecord'

    display_name = String(default=_('Attendance Record'))
    block_name = String(default=_('Attendance Record'))

    sessions = Dict(
        default={
            "nesting": 3,
            "sessions": {
                "Week 1": {
                    "Sunday": [
                        ["week1-sun-morning", "Morning Session"], 
                        ["week1-sun-evening", "Evening Session"]
                    ],
                    "Monday": [
                        ["week1-mon-morning", "Morning Session"],
                        ["week1-mon-evening", "Evening Session"]
                    ]
                },
                "Week 2": {
                    "Sunday": [
                        ["week2-sun-morning", "Morning Session"],
                        ["week2-sun-afternoon", "Afternoon Session"]
                    ],
                    "Wednesday": [
                        ["week2-wed-afternoon", "Afternoon Session"],
                        ["week2-wed-evening", "Evening Session"]
                    ]
                }
            }
        },
        scope=Scope.settings, help=_("Sessions in this record")
    )

    options = List(
        default=[
            ["not-recorded", "Not recorded"],
            ["attended", "Attended"],
            ["late", "Late"],
            ["absent", "Absent"]
        ], scope=Scope.settings, help=_("Options to choose from for each learner")
    )
    records = Dict(help=_("All learner' records"), scope=Scope.user_state_summary, default={"student_1": { "week1-sun-morning": "attended", "week2-sun-afternoon": "late", "week2-wed-afternoon": "absent" }})

    
    def get_headers_and_session_ids(self):
        session_ids = []
        header_rows = []
        if self.sessions['nesting'] == 1:
            header_rows.append([])
            header_rows.append([])
            header_rows.append(['user_id', 'username', 'user_email', *map(lambda el: el[1], self.sessions['sessions'])])
            session_ids = [*map(lambda el: el[0], self.sessions['sessions'])]
        elif self.sessions['nesting'] == 2:
            header_row1 = ["", "", ""]
            header_row2 = ['user_id', 'username', 'user_email']
            for key, session_values in self.sessions['sessions'].items():
                for i in session_values:
                    header_row1.append(key)
                header_row2 += [*map(lambda el: el[1], session_values)]
                session_ids += [*map(lambda el: el[0], session_values)]
            header_rows.append([])
            header_rows.append(header_row1)
            header_rows.append(header_row2)
        elif self.sessions['nesting'] == 3:
            header_row1 = ["", "", ""]
            header_row2 = ["", "", ""]
            header_row3 = ['user_id', 'username', 'user_email']
            for key, session_level_values in self.sessions['sessions'].items():
                for key2, session_values in session_level_values.items():
                    for i in session_level_values:
                        header_row1.append(key)
                        header_row2.append(key2)
                    header_row3 += [*map(lambda el: el[1], session_values)]
                    session_ids += [*map(lambda el: el[0], session_values)]
            header_rows.append(header_row1)
            header_rows.append(header_row2)
            header_rows.append(header_row3)
        return header_rows, session_ids


    def send_submit_event(self, record):
        # The SDK doesn't set url_name.
        event_dict = {'url_name': getattr(self, 'url_name', '')}
        event_dict.update(record)
        self.publish_event_from_dict(
            self.event_namespace + '.submitted',
            event_dict,
        )

    def object_to_json(self, obj):
        return json.dumps(obj)

    def json_string_to_object(self, json_string):
        return json.loads(json_string)
    
    def get_current_user_id(self):
        return self.runtime.user_id

    def get_learner_records(self):
        if self.can_view_records():
            return self.records
        else:
            return { f"{str(self.runtime.user_id)}": self.records[str(self.runtime.user_id)] }

    def can_submit(self):
        """
        Checks to see if the user is permitted to submit the records.
        """
        return self.can_view_records()

    def can_view_records(self):
        """
        Checks to see if the user has permissions to view all session records.
        This only works inside the LMS.
        """
        return True # TODO: testing
        if not hasattr(self.runtime, 'user_is_staff'):
            return False

        # Course staff users have permission to view results.
        if self.runtime.user_is_staff:
            return True

        # Check if user is member of a group that is explicitly granted
        # permission to view the results through django configuration.
        if not HAS_GROUP_PROFILE:
            return False

        group_names = getattr(settings, 'XBLOCK_ATTENDANCERECORD_EXTRA_SUBMIT_RECORDS_GROUPS', [])
        if not group_names:
            return False
        user = self.runtime.get_real_user(self.runtime.anonymous_student_id)
        group_ids = user.groups.values_list('id', flat=True)
        return GroupProfile.objects.filter(group_id__in=group_ids, name__in=group_names).exists()

    def author_view(self, context=None):
        """
        Used to hide CSV export in Studio view
        """
        if not context:
            context = {}

        context['studio_edit'] = True
        return self.student_view(context)

    def student_view(self, context=None):
        """
        The primary view of the AttendanceRecordXBlock, shown to learners
        when viewing courses.
        """
        if not context:
            context = {}

        _, session_ids = self.get_headers_and_session_ids()

        course_key = getattr(self.scope_ids.usage_id, 'course_key', None)
        
        if self.can_submit():
            enrollments = self.get_enrollments(course_key)
        else:
            enrollments = self.get_enrollments(course_key, user_ids=[self.runtime.user_id])

        learners = []
        for learner in enrollments:
            learners.append(learner)

        context.update({
            'sessions': self.sessions,
            'session_ids': session_ids,
            'options': self.options,
            'records': self.get_learner_records(),
            'learners': learners,
            'block_id': self._get_block_id(),
            'usage_id': six.text_type(self.scope_ids.usage_id),
            'can_submit': self.can_submit(),
            'can_view_records': self.can_view_records(),
            'block_name': self.block_name
        })

        return self.create_fragment(
            context,
            template="static/html/attendancerecord.html",
            css="static/css/attendancerecord.css",
            js="static/js/src/attendancerecord.js",
            js_init="AttendanceRecordXBlock"
        )

    def studio_view(self, context=None):
        if not context:
            context = {}

        context.update({
            'sessions': self.object_to_json(self.sessions),
            'options': self.object_to_json(self.options),
            'block_name': self.block_name
        })
        return self.create_fragment(
            context,
            template="static/html/attendancerecord_edit.html",
            css="static/css/attendancerecord_edit.css",
            js="static/js/src/attendancerecord_edit.js",
            js_init="AttendanceRecordEdit"
        )

    @XBlock.json_handler
    def submit(self, data, suffix=''):
        """
        Submit the user's answers
        """
        new_records = dict(data)
        result = {'success': True, 'errors': []}

        if not self.options:
            result['success'] = False
            result['errors'].append(self.ugettext("You must have at least one option to be able to save the learner records."))
            return result

        if not new_records:
            result['success'] = False
            result['errors'].append(self.ugettext("You must submit values for the learner records."))
            return result

        if not self.can_submit():
            result['success'] = False
            result['errors'].append(self.ugettext('You are not permitted to perform this action.'))
            return result

        options_map = dict(self.options)
        first_option = self.options[0]

        _, session_ids = self.get_headers_and_session_ids()


        session_ids_map = {}
        for session_id in session_ids: # just for efficiency
            session_ids_map[session_id] = 1

        clean_records = {}
        # Make sure the all submitted options are valid
        for student_id, student_record in new_records.items():
            clean_records[student_id] = {}
            for session_key, option in student_record.items():
                if session_key not in session_ids_map:
                    continue
                if option in options_map:
                    clean_records[student_id][session_key] = option
                else:
                    clean_records[student_id][session_key] = first_option[0]

        # Record the submission!
        self.records = clean_records
        self.send_submit_event({'records': self.records})

        return result

    @XBlock.json_handler
    def studio_submit(self, data, suffix=''):
        result = {'success': True, 'errors': []}
        sessions = data.get('sessions', '').strip()
        options = data.get('options', '').strip()
        block_name = data.get('block_name', '').strip()

        if not sessions:
            result['errors'].append(self.ugettext("You must add sessions."))
            result['success'] = False
        
        if not options:
            result['errors'].append(self.ugettext("You must add options."))
            result['success'] = False

        if not result['success']:
            return result

        self.sessions = self.json_string_to_object(sessions)
        self.options = self.json_string_to_object(options)
        self.block_name = block_name

        return result

    def prepare_data(self):
        """
        Return a two-dimensional list containing cells of data ready for CSV export.
        """
        header_rows, session_ids = self.get_headers_and_session_ids()

        data = {}
        options_map = dict(self.options)
        course_key = getattr(self.scope_ids.usage_id, 'course_key', None)
        enrollments = self.get_enrollments(course_key)
        for enrollment in enrollments:
            state = json.loads(sm.state)
            if enrollment['user_id'] not in data:
                row = [
                    enrollment['user_id'],
                    enrollment['username'],
                    enrollment['email']
                ]
                for session_id in self.session_ids:
                    student_records = self.records.get(enrollment['user_id'], {})
                    if session_id in student_records:
                        row.append(options_map[session_id])
                data[enrollment['user_id']] = row
        return header_row + list(data.values())

    def get_filename(self):
        """
        Return a string to be used as the filename for the CSV export.
        """
        return u"attendancerecord-data-export-{}.csv".format(time.strftime("%Y-%m-%d-%H%M%S", time.gmtime(time.time())))

    # TO-DO: change thi{s to create the scenarios you'd like to see in the
    # workbench while developing your XBlock.
    @staticmethod
    def workbench_scenarios():
        """A canned scenario for display in the workbench."""
        return [
            ("AttendanceRecordXBlock",
             """<attendancerecord/>
             """),
            ("Multiple AttendanceRecordXBlock",
             """<vertical_demo>
                <attendancerecord/>
                <attendancerecord/>
                <attendancerecord/>
                </vertical_demo>
             """),
        ]
