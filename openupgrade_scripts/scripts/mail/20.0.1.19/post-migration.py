# Copyright 2026 Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from openupgradelib import openupgrade

# 19.0 Font Awesome icon -> 20.0 Material Symbols icon. Applied only when the
# standard activity type still has the 19.0 default, so a custom icon survives.
_activity_icon_xmlids = {
    "mail.mail_activity_data_email": ("fa-envelope", "mail"),
    "mail.mail_activity_data_call": ("fa-phone", "phone"),
    "mail.mail_activity_data_meeting": ("fa-users", "calendar_today"),
    "mail.mail_activity_data_todo": ("fa-check", "check"),
    "mail.mail_activity_data_upload_document": ("fa-upload", "upload"),
    "mail.mail_activity_data_warning": ("fa-warning", "warning"),
}


def _update_activity_icons(env):
    for xmlid, (old_icon, new_icon) in _activity_icon_xmlids.items():
        activity_type = env.ref(xmlid, raise_if_not_found=False)
        if activity_type and activity_type.icon == old_icon:
            activity_type.icon = new_icon


def _update_subtypes(env):
    """Rename the standard subtypes and swap the note/activity sequences.

    Names are translated. Write them in en_US and only when the English source
    term is still the 19.0 value. Other languages keep their existing
    translations.
    """
    renames = {
        "mail.mt_comment": ("Discussions", "Messages", None),
        "mail.mt_note": ("Note", "Notes", (100, 90)),
        "mail.mt_activities": (None, None, (90, 100)),
    }
    for xmlid, (old_name, new_name, sequence_change) in renames.items():
        subtype = env.ref(xmlid, raise_if_not_found=False)
        if not subtype:
            continue
        if old_name and new_name:
            english = subtype.with_context(lang="en_US")
            if english.name == old_name:
                english.name = new_name
        if sequence_change and subtype.sequence == sequence_change[0]:
            subtype.sequence = sequence_change[1]


def _imply_internal_user_on_canned_response_admin(env):
    group = env.ref("mail.group_mail_canned_response_admin", raise_if_not_found=False)
    user_group = env.ref("base.group_user", raise_if_not_found=False)
    if group and user_group and user_group not in group.implied_ids:
        group.write({"implied_ids": [(4, user_group.id)]})


def _assign_channel_owners(env):
    """20.0 requires an owner to archive a channel or a group, and to edit a
    read-only channel. 19.0 had no roles. The user who created the channel
    becomes the owner when they are still a member; otherwise the oldest
    active internal member does. The standard #general admin membership is
    forced to owner, matching ``discuss_channel_data.xml``.
    """
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE discuss_channel_member AS member
           SET channel_role = 'owner'
          FROM discuss_channel AS channel
          JOIN res_users AS creator ON creator.id = channel.create_uid
         WHERE member.channel_id = channel.id
           AND member.partner_id = creator.partner_id
           AND channel.channel_type IN ('channel', 'group')
           AND member.channel_role IS NULL
        """,
    )
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE discuss_channel_member AS member
           SET channel_role = 'owner'
         WHERE member.id IN (
                SELECT DISTINCT ON (channel.id) candidate.id
                  FROM discuss_channel AS channel
                  JOIN discuss_channel_member AS candidate
                    ON candidate.channel_id = channel.id
                  JOIN res_users AS users
                    ON users.partner_id = candidate.partner_id
                   AND users.active
                 WHERE channel.channel_type IN ('channel', 'group')
                   AND NOT EXISTS (
                        SELECT 1
                          FROM discuss_channel_member AS owner
                         WHERE owner.channel_id = channel.id
                           AND owner.channel_role = 'owner'
                   )
                 ORDER BY channel.id, candidate.id
               )
        """,
    )
    # discuss_channel_data.xml makes the admin membership of #general the owner.
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE discuss_channel_member AS member
           SET channel_role = 'owner'
          FROM ir_model_data AS data
         WHERE data.module = 'mail'
           AND data.name = 'channel_member_general_channel_for_admin'
           AND data.model = 'discuss.channel.member'
           AND member.id = data.res_id
           AND member.channel_role IS DISTINCT FROM 'owner'
        """,
    )


@openupgrade.migrate()
def migrate(env, version):
    _update_activity_icons(env)
    _update_subtypes(env)
    _imply_internal_user_on_canned_response_admin(env)
    if openupgrade.column_exists(env.cr, "discuss_channel_member", "channel_role"):
        _assign_channel_owners(env)
