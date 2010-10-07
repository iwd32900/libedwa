/*
- add CSS classes, etc. to the table elements
- add support for other kinds of form elements (except file upload?)
- add a display-only view and allow toggling between edit and viewing mode
*/
if(!edwa) var edwa = {css_prefix: "edwa-"};
(function($) {
edwa.jsonforms = {
    next_id: 10000,
    // Allow each bit of initial data to be a simple value
    // or an object with attributes "value" and "errors".
    get_value: function(x) {
        if($.isPlainObject(x)) return x.value;
        else return x;
    },
    get_errors: function(x) {
        if($.isPlainObject(x)) return x.errors || [];
        else return [];
    },
    // Generate a simple label and corresponding HTML <INPUT> for one form field.
    // Actually, generate a function that will do that, when called with initial data.
    // data will be updated when the form value changes.
    make_input: function(name, label_text, help_text, input_str) {
        function handler(data) {
            var input = $(input_str);
            var input_id = "id_edwa_"+edwa.jsonforms.next_id;
            edwa.jsonforms.next_id += 1;
            input[0].id = input_id;
            var label_th = $("<th align='right'><div class='"+edwa.css_prefix+"label'><label for='"+input_id+"'>"+label_text+"</label></div></th>");
            var td = $("<td></td>");
            var input_div = $("<div class='"+edwa.css_prefix+"input'></div>");
            input_div.append(input);
            td.append(input_div);
            var msg_div = $("<div class='"+edwa.css_prefix+"msgs'></div>");
            if(help_text) {
                var help_div = $("<div class='"+edwa.css_prefix+"msgs'>"+help_text+"</div>");
                msg_div.append(help_div);
            }
            if(name in data) {
                // In Firefox, type is "select-one" or "select-multiple".
                if(/^select/.test(input[0].type)) {
                    // Make sure each value is in string format
                    var values = $.map(edwa.jsonforms.get_value(data[name]), function(elem, idx) { return ""+elem; });
                    // Set the selected status of each option in the select
                    $("option", input).each(function() { this.selected = ($.inArray(this.value, values) != -1); });
                } else if(input[0].type == "checkbox" || input[0].type == "radio") {
                    input[0].checked = edwa.jsonforms.get_value(data[name]);
                } else {
                    input[0].value = edwa.jsonforms.get_value(data[name]);
                }
                var errs = edwa.jsonforms.get_errors(data[name]);
                if(errs.length) {
                    var err_ul = $("<ul></ul>");
                    for(var ii in errs) {
                        err_ul.append($("<li>"+errs[ii]+"</li>"));
                    }
                    var err_div = $("<div class='"+edwa.css_prefix+"error'></div>");
                    err_div.append(err_ul);
                    msg_div.append(err_div);
                }
                // Once we've displayed the errors initially, simplify the structure of the JSON again.
                data[name] = edwa.jsonforms.get_value(data[name]) || "";
            }
            td.append(msg_div);
            input.change(function() {
                if(/^select/.test(this.type)) {
                    // Iterate through each choice, adding selected ones to the list of values.
                    var vals = [];
                    $("option", this).each(function() {
                        if(this.selected) vals.push(this.value);
                    });
                    data[name] = vals;
                }
                else if(this.type == "checkbox" || this.type == "radio") data[name] = this.checked;
                else data[name] = this.value;
            }).change(); // need to trigger fake change to sync single SELECTs that start with empty value
            var tr = $("<tr valign='top'></tr>");
            if(input[0].type != "hidden") tr.append(label_th);
            else tr.append("<th align='right'><div class='"+edwa.css_prefix+"label'></th>");
            tr.append(td);
            return tr;
        }
        return handler;
    },
    // Generate a list of nested forms, where one can add and remove items from the list.
    // Actually, generate a function that will do that, when called with initial data.
    // all_data will be updated when the form values change.
    makeNestedForm: function(name, label, template, extras) {
        var extras = $.extend({
            allow_add: true,
            allow_remove: true,
            add_icon: "(+)",
            remove_icon: "(-)",
            _return_td: false
        }, extras);
        function handler(all_data) {
            if(!(name in all_data)) all_data[name] = [];
            // Extract the errors, if any, then simplify the JSON structure.
            var errs = edwa.jsonforms.get_errors(all_data[name]);
            var data_list = edwa.jsonforms.get_value(all_data[name]) || [];
            all_data[name] = data_list;
            var td = $("<td></td>")
            var input_div = $("<div class='"+edwa.css_prefix+"input'></div>");
            td.append(input_div);
            // Make a <TABLE> containing one complete set of form fields,
            // along with a link to remove that set of fields.
            function make_table(data, allow_remove) {
                var table = $("<table border='0' cellspacing='0' cellpadding='0' class='"+edwa.css_prefix+"nform'></table>");
                var nrows = 0;
                for(var fieldname in template) {
                    var row = template[fieldname](data);
                    table.append(row);
                    nrows += 1;
                }
                var remove_this = $("<a href='' class='"+edwa.css_prefix+"rm1'>"+extras.remove_icon+"</a>").click(function() {
                    var ii = $.inArray(data, data_list); // == indexOf
                    if(ii < 0 && console) console.log("Whoa -- can't find form item to remove it!");
                    data_list.splice(ii, 1);
                    table.remove();
                    return false;
                });
                if(allow_remove) {
                    $("tr", table).first().prepend($("<td rowspan='"+nrows+"'></td>").append(remove_this));
                }
                // For any SELECTs that are marked with CSS class "edwa-new-and-used",
                // hide the other fields in that subform UNLESS the value is 0.
                // This facilitates either choosing between existing objects
                // or creating a new object. (Editing an existing object is not supported.)
                $("."+edwa.css_prefix+"new-and-used", table).bind("change", function() {
                    if(this.value == 0) {
                        $("tr", $(this).closest("table")).show();
                    } else {
                        var my_tr = $(this).closest("tr");
                        $("tr", $(this).closest("table")).not(my_tr).hide();
                    }
                }).change(); // initial sync
                return table;
            }
            // For each item in the list of initial values, construct a <TABLE>
            // with a full complement of fields.
            for(ii in data_list) {
                var data = data_list[ii];
                // Fields created from initialization data may or may not be removable.
                input_div.append(make_table(data, extras.allow_remove));
            }
            // Create a link that will add a (blank) item to the list.
            var add_one = $("<a href='' class='"+edwa.css_prefix+"add1'>"+extras.add_icon+"</a>").click(function() {
                var data = {};
                data_list.push(data);
                // Newly created entries are always removable before form is submitted.
                $(this).before(make_table(data, true));
                return false;
            });
            if(extras.allow_add) {
                input_div.append(add_one); // below list of forms
            }
            if(errs.length) {
                var err_ul = $("<ul></ul>");
                for(var ii in errs) {
                    err_ul.append($("<li>"+errs[ii]+"</li>"));
                }
                var err_div = $("<div class='"+edwa.css_prefix+"error'></div>");
                err_div.append(err_ul);
                var msg_div = $("<div class='"+edwa.css_prefix+"msgs'></div>");
                msg_div.append(err_div);
                td.append(msg_div);
            }
            var label_td = $("<th align='right'><div class='"+edwa.css_prefix+"label'> "+label+" </th>");
            var row = $("<tr valign='top'></tr>").append(label_td).append(td);
            if(extras._return_td) return td;
            else return row;
        }
        return handler;
    },
    // Re-use machinery from above to create layout for outer object.
    // To be proper JSON, this must be a single object -- no adding/removing from a list!
    make_jsonform: function(data, template, extras) {
        var extras = $.extend(extras, {
            allow_add: false,
            allow_remove: false,
            _return_td: true
        });
        var data = edwa.jsonforms.get_value(data);
        if(data.length == 0) data.push( {} );
        var td = edwa.jsonforms.makeNestedForm("x", "x", template, extras)({x:data});
        return td.children().first().children(); // all DOM elements in the DIV in the second top-level TD
    }
};
})(jQuery);
