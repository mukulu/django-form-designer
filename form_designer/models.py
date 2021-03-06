import re

from django.conf import settings as django_settings
from django.core.mail import send_mail
from django.db import models
from django.utils.translation import ugettext_lazy as _

from picklefield.fields import PickledObjectField

from form_designer import settings
from form_designer.fields import TemplateTextField, TemplateCharField, ModelNameField
from form_designer.utils import get_class

class FormDefinition(models.Model):
    name = models.SlugField(_('Name'), max_length=255, unique=True)
    title = models.CharField(_('Title'), max_length=255, blank=True, null=True)
    action = models.URLField(_('Target URL'), max_length=255, blank=True, null=True, help_text=_('If you leave this empty, the page where the form resides will be requested, and you can use the mail form and logging features. You can also send data to external sites: For instance, enter "http://www.google.ch/search" to create a search form.'))
    mail_to = TemplateCharField(_('Send form data to e-mail address'), max_length=255, blank=True, null=True, help_text=('Separate several addresses with a comma. Your form fields are available as template context. Example: "admin@domain.com, {{ from_email }}" if you have a field named `from_email`.'))
    mail_from = TemplateCharField(_('Sender address'), max_length=255, blank=True, null=True, help_text=('Your form fields are available as template context. Example: "{{ firstname }} {{ lastname }} <{{ from_email }}>" if you have fields named `first_name`, `last_name`, `from_email`.'))
    mail_subject = TemplateCharField(_('e-Mail subject'), max_length=255, blank=True, null=True, help_text=('Your form fields are available as template context. Example: "Contact form {{ subject }}" if you have a field named `subject`.'))
    method = models.CharField(_('Method'), max_length=10, default="POST", choices = (('POST', 'POST'), ('GET', 'GET')))
    success_message = models.CharField(_('Success message'), max_length=255, blank=True, null=True)
    error_message = models.CharField(_('Error message'), max_length=255, blank=True, null=True)
    submit_label = models.CharField(_('Submit button label'), max_length=255, blank=True, null=True)
    log_data = models.BooleanField(_('Log form data'), default=True, help_text=_('Logs all form submissions to the database.'))
    success_redirect = models.BooleanField(_('Redirect after success'), default=False)
    success_clear = models.BooleanField(_('Clear form after success'), default=True)
    allow_get_initial = models.BooleanField(_('Allow initial values via URL'), default=True, help_text=_('If enabled, you can fill in form fields by adding them to the query string.'))
    message_template = TemplateTextField(_('Message template'), blank=True, null=True, help_text=_('Your form fields are available as template context. Example: "{{ message }}" if you have a field named `message`. To iterate over all fields, use the variable `data` (a list containing a dictionary for each form field, each containing the elements `name`, `label`, `value`).'))
    form_template_name = models.CharField(_('Form template'), max_length=255, choices=settings.FORM_TEMPLATES, blank=True, null=True)

    class Meta:
        verbose_name = _('Form')
        verbose_name_plural = _('Forms')

    def get_field_dict(self):
        dict = {}
        for field in self.formdefinitionfield_set.all():
            dict[field.name] = field
        return dict

    def get_form_data(self, form):
        data = []
        field_dict = self.get_field_dict()
        form_keys = form.fields.keys()
        def_keys = field_dict.keys()
        for key in form_keys:
            if key in def_keys and field_dict[key].include_result:
                value = form.cleaned_data[key]
                if getattr(value, '__form_data__', False):
                    value = value.__form_data__()
                data.append({'name': key, 'label': form.fields[key].label, 'value': value})
        return data

    def get_form_data_dict(self, form_data):
        dict = {}
        for field in form_data:
            dict[field['name']] = field['value']
        return dict

    def compile_message(self, form_data, template=None):
        from django.template import Context, Template
        from django.template.loader import get_template
        if template:
            t = get_template(template)
        elif not self.message_template:
            t = get_template('txt/formdefinition/data_message.txt')
        else:
            t = Template(self.message_template)
        context = Context(self.get_form_data_dict(form_data))
        context['data'] = form_data
        return t.render(context)

    def count_fields(self):
        return self.formdefinitionfield_set.count()
    count_fields.short_description = _('Fields')

    def __unicode__(self):
        return self.title or self.name

    def log(self, form):
        form_data = self.get_form_data(form)
        #if self.mail_to:
        #    form_data.append({'name': 'mail', 'label': 'mail', 'value': self.compile_message(form_data)})
        FormLog(form_definition=self, data=form_data).save()

    def string_template_replace(self, text, context_dict):
        from django.template import Context, Template, TemplateSyntaxError
        try:
            t = Template(text)
            return t.render(Context(context_dict))
        except TemplateSyntaxError:
            return text

    def send_mail(self, form):
        form_data = self.get_form_data(form)
        message = self.compile_message(form_data)
        context_dict = self.get_form_data_dict(form_data)

        mail_to = re.compile('\s*[,;]+\s*').split(self.mail_to)
        for key, email in enumerate(mail_to):
            mail_to[key] = self.string_template_replace(email, context_dict)

        mail_from = self.mail_from or None
        if mail_from:
            mail_from = self.string_template_replace(mail_from, context_dict)

        if self.mail_subject:
            mail_subject = self.string_template_replace(self.mail_subject, context_dict)
        else:
            mail_subject = self.title

        import logging
        logging.debug('Mail: '+repr(mail_from)+' --> '+repr(mail_to));

        send_mail(mail_subject, message, mail_from or None, mail_to, fail_silently=False)

    @property
    def submit_flag_name(self):
        name = settings.SUBMIT_FLAG_NAME % self.name
        while self.formdefinitionfield_set.filter(name__exact=name).count() > 0:
            name += '_'
        return name

class FormLog(models.Model):
    created = models.DateTimeField(_('Created'), auto_now=True)
    form_definition = models.ForeignKey(FormDefinition, verbose_name=_('Form'))
    data = PickledObjectField(_('Data'), null=True, blank=True)

    class Meta:
        verbose_name = _('Form log')
        verbose_name_plural = _('Form logs')
        ordering = ['-created']

class AbstractField(models.Model):
    """
    Allows our form fields to be used outside of a standard for and allow
    addition attirubutes for a model
    """
    name = models.SlugField(_('name'), max_length=255)
    field_class = models.CharField(_('Field class'), choices=settings.FIELD_CLASSES, max_length=32)
    required = models.BooleanField(_('required'), default=True)
    initial = models.TextField(_('initial value'), blank=True, null=True)

    # Display
    label = models.CharField(_('label'), max_length=255, blank=True, null=True)
    widget = models.CharField(_('widget'), default='', choices=settings.WIDGET_CLASSES, max_length=255, blank=True, null=True)
    help_text = models.CharField(_('help text'), max_length=255, blank=True, null=True)
    position = models.IntegerField(_('Position'), default=0)

    # Text
    max_length = models.IntegerField(_('Max. length'), blank=True, null=True)
    min_length = models.IntegerField(_('Min. length'), blank=True, null=True)

    # Numbers
    max_value = models.FloatField(_('Max. value'), blank=True, null=True)
    min_value = models.FloatField(_('Min. value'), blank=True, null=True)
    max_digits = models.IntegerField(_('Max. digits'), blank=True, null=True)
    decimal_places = models.IntegerField(_('Decimal places'), blank=True, null=True)

    # Regex
    regex = models.CharField(_('Regular Expression'), max_length=255, blank=True, null=True)

    # Choices
    choice_values = models.TextField(_('Values'), blank=True, null=True, help_text=_('One value per line'))
    choice_labels = models.TextField(_('Labels'), blank=True, null=True, help_text=_('One label per line'))

    # Model Choices
    choice_model_choices = settings.CHOICE_MODEL_CHOICES
    choice_model = ModelNameField(_('Data model'), max_length=255, blank=True, null=True, choices=choice_model_choices, help_text=('your_app.models.ModelName' if not choice_model_choices else None))
    choice_model_empty_label = models.CharField(_('Empty label'), max_length=255, blank=True, null=True)

    class Meta:
        abstract = True

    # def ____init__(self, field_class=None, name=None, required=None, widget=None, label=None, initial=None, help_text=None, *args, **kwargs):
    #     super(FormDefinitionField, self).__init__(*args, **kwargs)
    #     self.name = name
    #     self.field_class = field_class
    #     self.required = required
    #     self.widget = widget
    #     self.label = label
    #     self.initial = initial
    #     self.help_text = help_text

    def __unicode__(self):
        return self.label if self.label else self.name

    def get_form_field_init_args(self):
        args = {
            'required': self.required,
            'label': self.label if self.label else '',
            'initial': self.initial if self.initial else None,
            'help_text': self.help_text,
        }

        field_class = self.field_class.split('.')[-1]

        if field_class in ('CharField', 'EmailField', 'RegexField'):
            args.update({
                'max_length': self.max_length,
                'min_length': self.min_length,
            })

        if field_class in ('IntegerField', 'DecimalField'):
            args.update({
                'max_value': int(self.max_value) if self.max_value != None else None,
                'min_value': int(self.min_value) if self.min_value != None else None,
            })

        if field_class in ('DecimalField',):
            args.update({
                'max_value': self.max_value,
                'min_value': self.min_value,
                'max_digits': self.max_digits,
                'decimal_places': self.decimal_places,
            })

        if field_class in ('RegexField',):
            if self.regex:
                args.update({
                    'regex': self.regex
                })

        if field_class in ('ChoiceField', 'MultipleChoiceField'):
            if self.choice_values:
                choices = []
                regex = re.compile('[\s]*\n[\s]*')
                values = regex.split(self.choice_values)
                labels = regex.split(self.choice_labels) if self.choice_labels else []
                for index, value in enumerate(values):
                    try:
                        label = labels[index]
                    except:
                        label = value
                    choices.append((value, label))
                args.update({
                    'choices': tuple(choices)
                })

        if field_class in ('ModelChoiceField', 'ModelMultipleChoiceField'):
            print self.choice_model, ModelNameField.get_model_from_string(self.choice_model)
            args.update({
                'queryset': ModelNameField.get_model_from_string(self.choice_model).objects.all()
            })

        if field_class in ('ModelChoiceField',):
            args.update({
                'empty_label': self.choice_model_empty_label
            })

        if self.widget:
            args.update({
                'widget': get_class(self.widget)()
            })

        return args

class FormDefinitionField(AbstractField):
    form_definition = models.ForeignKey(FormDefinition)
    include_result = models.BooleanField(_('Include in result'), default=True, help_text=('If this is disabled, the field value will not be included in logs and e-mails generated from form data.'))

    class Meta:
        verbose_name = _('Field')
        verbose_name_plural = _('Fields')
        ordering = ['position']


if 'cms' in django_settings.INSTALLED_APPS:
    from cms.models import CMSPlugin

    class CMSFormDefinition(CMSPlugin):
        form_definition = models.ForeignKey(FormDefinition, verbose_name=_('Form'))

        def __unicode__(self):
            return self.form_definition.__unicode__()


if 'south' in django_settings.INSTALLED_APPS:
    from south.modelsinspector import add_introspection_rules
    add_introspection_rules([], ["^form_designer\.fields\..*"])
