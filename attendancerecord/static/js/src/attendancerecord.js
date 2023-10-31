/* Javascript for AttendanceRecordXBlock. */

function AttendanceRecordXBlock(runtime, element) {
    var self = this;
    var exportStatus = {};

    this.getRecords = function() {
        // Group records by learner id
        let records = {};
        this.selects.each((_index, el) => {
            const split_id = el.id.split('##');
            if (!(split_id[0] in records))
                records[split_id[0]] = {}
            records[split_id[0]][split_id[1]] = el.value // selected option
        });
        
        return records;
    };

    this.init = function() {
        // Initialization function for the Advanced Survey Block
        this.submitUrl = runtime.handlerUrl(element, 'submit');
        this.csv_url= runtime.handlerUrl(element, 'csv_export');

        this.submit = $('input[type=button]', element);
        this.exportResultsButton = $('.export-results-button', element);
        this.exportResultsButton.click(this.exportCsv);

        this.downloadResultsButton = $('.download-results-button', element);
        this.downloadResultsButton.click(this.downloadCsv);

        this.errorMessage = $('.error-message', element);
        this.feedback = $('#submit-feedback', element);

        this.selects = $('select', element);

        // If user is unable to modify records, disable input.
        if (! $('div.attendancerecord_block', element).data('can-submit')) {
            this.selects.attr('disabled', true);
            return
        }
        if (self.submit) {
            self.submit.click(function () {
                // Disable the submit button to avoid multiple clicks
                self.disableSubmit();
                $.ajax({
                    type: "POST",
                    url: self.submitUrl,
                    data: JSON.stringify(self.getRecords()),
                    success: self.onSubmit
                })
            });
        }
    };


    this.onSubmit = function (data) {
        // Fetch the results from the server and render them.
        if (!data['success']) {
            alert(data['errors'].join('\n'));
        }
        self.enableSubmit();
        if (data['success'])
            self.feedback.removeClass("attendancerecord-hidden");
        return;
    };

    this.disableSubmit = function() {
        // Disable the submit button.
        self.submit.attr("disabled", true);
    }

    this.enableSubmit = function () {
        // Enable the submit button.
        self.submit.removeAttr("disabled");
    };

    function getStatus() {
        $.ajax({
            type: 'POST',
            url: runtime.handlerUrl(element, 'get_export_status'),
            data: '{}',
            success: updateStatus,
            dataType: 'json'
        });
    }

    function updateStatus(newStatus) {
        var statusChanged = ! _.isEqual(newStatus, exportStatus);
        exportStatus = newStatus;
        if (exportStatus.export_pending) {
            // Keep polling for status updates when an export is running.
            setTimeout(getStatus, 1000);
        }
        else {
            if (statusChanged) {
                if (newStatus.last_export_result.error) {
                    self.errorMessage.text("Error: " + newStatus.last_export_result.error);
                    self.errorMessage.show();
                } else {
                    self.downloadResultsButton.attr('disabled', false);
                    self.errorMessage.hide()
                }
            }
        }
    }

    this.exportCsv = function() {
        $.ajax({
            type: "POST",
            url: self.csv_url,
            data: JSON.stringify({}),
            success: updateStatus
        });
    };

    this.downloadCsv = function() {
        window.location = exportStatus.download_url;
    };

    $(function ($) {
        /* Here's where you'd do things on page load. */
        self.init();
    });
}
