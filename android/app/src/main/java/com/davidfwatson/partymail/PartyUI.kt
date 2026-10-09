package com.davidfwatson.partymail

import android.app.Activity
import android.app.DatePickerDialog
import android.app.TimePickerDialog
import android.content.Context
import android.content.Intent
import android.graphics.BitmapFactory
import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import android.webkit.*
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.*
import java.net.HttpURLConnection
import java.net.URL
import java.time.LocalDate
import java.time.LocalTime
import java.time.format.DateTimeFormatter

private val Light = lightColorScheme(primary = Color(0xFF974065), secondary = Color(0xFF78624F), tertiary = Color(0xFF785B9E), background = Color(0xFFFFFAF7), surface = Color(0xFFFFFAF7), surfaceContainer = Color(0xFFF5ECE8))
private val Dark = darkColorScheme(primary = Color(0xFFECA7C6), secondary = Color(0xFFD1B69E), tertiary = Color(0xFFD2BBF6), background = Color(0xFF201A1D), surface = Color(0xFF201A1D), surfaceContainer = Color(0xFF30282C))

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun PartyApp(vm: PartyModel, activity: Activity) {
    MaterialTheme(colorScheme = if (isSystemInDarkTheme()) Dark else Light) {
        var confirm by remember { mutableStateOf<Pair<String, () -> Unit>?>(null) }
        val ask: (String, () -> Unit) -> Unit = { label, action -> confirm = label to action }
        BackHandler(enabled = vm.page != Page.HOME && vm.page != Page.LOGIN) { if (!vm.busy) vm.back() }
        Scaffold(
            topBar = {
                TopAppBar(title = { Text(when(vm.page) { Page.HOME -> "Party Mail"; Page.LOGIN -> "Welcome to Party Mail"; Page.EVENT -> "Your event"; Page.EDITOR -> if (vm.editor?.id.isNullOrBlank()) "Create an invitation" else "Edit invitation"; Page.INVITATION -> "You're invited"; Page.RESPONSE -> if (vm.responseToken == null) "Your RSVP" else "Update your RSVP"; Page.SETTINGS -> "People & access"; Page.SIGNIN -> "Confirm sign-in"; Page.ENROLL -> "Join Party Mail"; Page.PREVIEW -> "Invitation preview" }, fontFamily = FontFamily.Serif) },
                    navigationIcon = { if (vm.page != Page.HOME && vm.page != Page.LOGIN) TextButton(onClick = { if (vm.page == Page.EDITOR) ask("Discard unsaved changes?") { vm.back() } else vm.back() }, enabled = !vm.busy) { Text("Back") } },
                    actions = { if (vm.page == Page.HOME) TextButton(onClick = vm::showSettings, enabled = !vm.busy) { Text("Settings") } })
            },
            bottomBar = {
                if (vm.page == Page.EDITOR || vm.page == Page.RESPONSE) Surface(tonalElevation = 3.dp) {
                    // RSVP button lives in its form so the current local draft is available.
                    if (vm.page == Page.EDITOR) Button(onClick = vm::save, enabled = !vm.busy, modifier = Modifier.fillMaxWidth().navigationBarsPadding().padding(16.dp)) { Text(if (vm.busy) "Saving…" else "Save invitation") }
                }
            }
        ) { padding ->
            Column(Modifier.fillMaxSize().padding(padding)) {
                if (vm.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
                vm.error?.let { message -> MessageCard(message, true, vm::dismissError) }
                vm.notice?.let { message -> MessageCard(message, false, vm::dismissNotice) }
                if (!vm.bootstrapped) {
                    Column(Modifier.padding(28.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                        Text("Preparing your invitations…", style = MaterialTheme.typography.titleLarge)
                        if (!vm.busy) Button(onClick = vm::retryStartup) { Text("Retry connection") }
                    }
                } else when(vm.page) {
                    Page.HOME -> Dashboard(vm)
                    Page.LOGIN -> LoginScreen(vm, activity)
                    Page.EVENT -> EventScreen(vm, ask)
                    Page.EDITOR -> EditorScreen(vm)
                    Page.INVITATION -> InvitationScreen(vm, false)
                    Page.PREVIEW -> RenderedPreview(vm)
                    Page.RESPONSE -> ResponseScreen(vm)
                    Page.SETTINGS -> SettingsScreen(vm, activity, ask)
                    Page.SIGNIN -> SignInScreen(vm)
                    Page.ENROLL -> EnrollScreen(vm, activity)
                }
            }
        }
        confirm?.let { (label, action) -> AlertDialog(onDismissRequest = { confirm = null }, title = { Text(label) }, text = { Text("This change takes effect immediately.") }, confirmButton = { TextButton(onClick = { confirm = null; action() }) { Text("Confirm") } }, dismissButton = { TextButton(onClick = { confirm = null }) { Text("Cancel") } }) }
    }
}

@Composable private fun MessageCard(message: String, error: Boolean, dismiss: () -> Unit) {
    Surface(color = if (error) MaterialTheme.colorScheme.errorContainer else MaterialTheme.colorScheme.secondaryContainer, shape = RoundedCornerShape(12.dp), modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth()) {
        Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) { Text(message, Modifier.weight(1f)); TextButton(onClick = dismiss) { Text("Dismiss") } }
    }
}
@Composable private fun Body(content: @Composable ColumnScope.() -> Unit) { Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp), content = content) }
@Composable private fun Heading(title: String, subtitle: String? = null) { Column(verticalArrangement = Arrangement.spacedBy(6.dp)) { Text(title, style = MaterialTheme.typography.headlineSmall, fontFamily = FontFamily.Serif); subtitle?.let { Text(it, color = MaterialTheme.colorScheme.onSurfaceVariant) } } }
@Composable private fun Panel(content: @Composable ColumnScope.() -> Unit) { Card(shape = RoundedCornerShape(20.dp), modifier = Modifier.fillMaxWidth()) { Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp), content = content) } }
@Composable private fun Field(value: String, change: (String) -> Unit, label: String, modifier: Modifier = Modifier, enabled: Boolean = true, singleLine: Boolean = true, keyboard: KeyboardType = KeyboardType.Text, help: String? = null) {
    OutlinedTextField(value = value, onValueChange = change, label = { Text(label) }, modifier = modifier.fillMaxWidth(), enabled = enabled, singleLine = singleLine, minLines = if (singleLine) 1 else 4, keyboardOptions = KeyboardOptions(keyboardType = keyboard), supportingText = help?.let { { Text(it) } }, shape = RoundedCornerShape(12.dp))
}
@Composable private fun Toggle(label: String, value: Boolean, change: (Boolean) -> Unit, enabled: Boolean = true) { Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) { Text(label, Modifier.weight(1f)); Switch(checked = value, onCheckedChange = change, enabled = enabled) } }
@Composable private fun Choices(label: String, selected: String, values: List<String>, change: (String) -> Unit, enabled: Boolean = true) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) { Text(label, style = MaterialTheme.typography.labelLarge); FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) { values.forEach { value -> FilterChip(selected = selected == value, onClick = { change(value) }, label = { Text(value.replaceFirstChar(Char::titlecase)) }, enabled = enabled) } } }
}
private fun dateLabel(e: Event): String = runCatching { LocalDate.parse(e.date).format(DateTimeFormatter.ofPattern("EEEE, MMMM d, yyyy")) }.getOrDefault(e.date)
private fun timeLabel(value: String): String = runCatching { LocalTime.parse(value).format(DateTimeFormatter.ofPattern("h:mm a")) }.getOrDefault(value)
private fun share(context: Context, text: String, title: String = "Share invitation") { context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text), title)) }
internal fun openWeb(context: Context, url: String) {
    // Resolve a browser explicitly, so verified Party Mail app links cannot reopen this app.
    val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url)).apply {
        selector = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_APP_BROWSER)
    }
    runCatching { context.startActivity(intent) }.onFailure {
        android.widget.Toast.makeText(context, "Install or enable a browser to open this page.", android.widget.Toast.LENGTH_LONG).show()
    }
}
private fun eventURL(vm: PartyModel, e: Event) = if (Links.safeWeb(e.public_url, vm.api.origin)) e.public_url else "${vm.api.origin}/${e.slug}"

@Composable private fun Dashboard(vm: PartyModel) {
    var archived by rememberSaveable { mutableStateOf(false) }
    var search by rememberSaveable { mutableStateOf("") }
    val list = vm.events.filter { it.archived == archived && (search.isBlank() || it.name.contains(search, true) || it.location.contains(search, true)) }.sortedWith(compareBy<Event> { it.date }.thenBy { it.start_time })
    Body {
        Heading("Good things start with an invitation.", "Welcome, ${vm.session?.admin?.name.orEmpty()}. Plan your next gathering and keep every response in one place.")
        Button(onClick = vm::create, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) { Text("Create an event") }
        Field(search, { search = it }, "Search events")
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) { FilterChip(selected = !archived, onClick = { archived = false }, label = { Text("Upcoming & past") }); FilterChip(selected = archived, onClick = { archived = true }, label = { Text("Archived") }); Spacer(Modifier.weight(1f)); TextButton(onClick = vm::refreshEvents, enabled = !vm.busy) { Text("Refresh") } }
        if (list.isEmpty()) Panel { Heading(if (archived) "Your archive is empty" else "Your next party belongs here", if (search.isNotBlank()) "No events match your search." else "Create an invitation to get started.") }
        list.forEach { e -> Card(onClick = { vm.showEvent(e.slug) }, enabled = !vm.busy, shape = RoundedCornerShape(20.dp), modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(e.name, style = MaterialTheme.typography.titleLarge, fontFamily = FontFamily.Serif)
                Text("${dateLabel(e)} · ${timeLabel(e.start_time)}", style = MaterialTheme.typography.bodyMedium)
                Text(e.location, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text("${e.stats.attending} guests · ${e.stats.responses} responses", fontWeight = FontWeight.Medium, color = MaterialTheme.colorScheme.primary)
            }
        } }

    }
}

@Composable private fun LoginScreen(vm: PartyModel, activity: Activity) {
    var password by remember { mutableStateOf("") }
    var recovery by rememberSaveable { mutableStateOf(false) }
    var link by remember { mutableStateOf("") }
    val context = LocalContext.current
    Body {
        Heading("Make getting together feel special.", "Beautiful invitations. Simple RSVPs. A little more time with your favorite people.")
        Panel {
            Text("For hosts", style = MaterialTheme.typography.titleLarge)
            Button(onClick = { vm.passkeyLogin(activity) }, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) { Text("Sign in with a passkey") }
            TextButton(onClick = { recovery = !recovery }) { Text("Owner recovery") }
            if (recovery) {
                Text("Use the owner's recovery password. Other administrators can ask the owner for a one-use sign-in link.", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(password, { password = it }, modifier = Modifier.fillMaxWidth(), label = { Text("Owner password") }, visualTransformation = PasswordVisualTransformation(), singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), enabled = !vm.busy)
                Button(onClick = { val entered = password; password = ""; vm.login(entered) }, enabled = !vm.busy && password.isNotEmpty()) { Text("Sign in") }
            }
        }
        Panel {
            Text("Have an invitation?", style = MaterialTheme.typography.titleLarge)
            Text("Open a Party Mail link from a message, or paste it here. Administrator invitations and RSVP update links work too.")
            Field(link, { link = it }, "Party Mail link", keyboard = KeyboardType.Uri)
            OutlinedButton(onClick = { vm.openRaw(link); link = "" }, enabled = !vm.busy && link.isNotBlank(), modifier = Modifier.fillMaxWidth()) { Text("Open link") }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) { TextButton(onClick = { openWeb(context, "${vm.api.origin}/privacy") }) { Text("Privacy") }; TextButton(onClick = { openWeb(context, "${vm.api.origin}/terms") }) { Text("Terms") } }
    }
}
@Composable private fun SignInScreen(vm: PartyModel) { Body { Heading("Sign in on this device?", "This private link grants administrator access and can be used once. Continue only if you expected it from the owner."); Button(onClick = vm::confirmSignIn, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) { Text("Confirm and use this sign-in link") }; OutlinedButton(onClick = vm::home, enabled = !vm.busy) { Text("Cancel") } } }
@Composable private fun EnrollScreen(vm: PartyModel, activity: Activity) {
    var name by rememberSaveable { mutableStateOf("") }
    Body { Heading("You're invited to help host.", "Create an administrator account with a passkey. The invitation is consumed only after your passkey is registered."); Field(name, { name = it }, "Your name", enabled = !vm.busy); Button(onClick = { vm.enroll(activity, name) }, enabled = !vm.busy && name.isNotBlank(), modifier = Modifier.fillMaxWidth()) { Text("Create account with a passkey") } }
}

@Composable private fun EventScreen(vm: PartyModel, ask: (String, () -> Unit) -> Unit) {
    val e = vm.event ?: return
    val context = LocalContext.current
    var email by rememberSaveable(e.slug) { mutableStateOf("") }
    var filter by rememberSaveable(e.slug) { mutableStateOf("all") }
    var search by rememberSaveable(e.slug) { mutableStateOf("") }
    val list = vm.responses.filter { (filter == "all" || it.attending == filter) && (search.isBlank() || it.name.contains(search, true) || it.email.contains(search, true)) }
    Body {
        Heading(e.name, "${dateLabel(e)} · ${timeLabel(e.start_time)}${if (e.end_time.isBlank()) "" else " – ${timeLabel(e.end_time)}"}")
        Text(e.location)
        if (e.archived) MessageCard("Archived. Restore this event to accept RSVPs and send invitations.", false, {})
        Panel {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Metric("Guests", e.stats.attending); Metric("Responses", e.stats.responses); Metric("Yes", e.stats.accepted); Metric("No", e.stats.declined)
            }
        }
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = vm::edit, enabled = !vm.busy) { Text("Edit invitation") }
            OutlinedButton(onClick = vm::preview, enabled = !vm.busy) { Text("Preview") }
            OutlinedButton(onClick = { share(context, "You're invited to ${e.name}! ${eventURL(vm, e)}") }, enabled = !vm.busy && !e.archived) { Text("Share invite") }
            OutlinedButton(onClick = { ask(if (e.archived) "Restore this event?" else "Archive this event?") { vm.archive() } }, enabled = !vm.busy) { Text(if (e.archived) "Restore" else "Archive") }
        }
        if (!e.archived) Panel {
            Text("Invite someone", style = MaterialTheme.typography.titleMedium)
            if (vm.session?.email_enabled == true && vm.session?.email_connected == true) {
                Field(email, { email = it }, "Email address", keyboard = KeyboardType.Email, enabled = !vm.busy)
                Button(onClick = { vm.sendInvite(email) }, enabled = !vm.busy && email.isNotBlank()) { Text("Send email invitation") }
            } else Text("Email sending is unavailable. Share your invitation link with guests.")
            Text(eventURL(vm, e), style = MaterialTheme.typography.bodySmall)
        }
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) { Text("Guest responses", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f)); TextButton(onClick = { vm.export(context) }, enabled = !vm.busy) { Text("Export CSV") } }
        Field(search, { search = it }, "Search guests")
        Choices("Show", filter, listOf("all", "yes", "no"), { filter = it })
        if (list.isEmpty()) Text(if (vm.responses.isEmpty()) "Your first response will appear here." else "No matching responses.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        list.forEach { r -> Panel {
            Row { Text(r.name, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f)); Text(if (r.attending == "yes") "Attending" else "Declined", color = MaterialTheme.colorScheme.primary) }
            Text(r.email)
            if (r.attending == "yes") Text("${r.num_adults} adults · ${r.num_children} children")
            if (r.dietary_restrictions.isNotBlank()) Text("Dietary needs: ${r.dietary_restrictions}")
            if (r.comment.isNotBlank()) Text(r.comment)
            Text("Updated ${r.updated_at.ifBlank { r.timestamp }.replace('T', ' ').substringBefore('.')}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        } }
        OutlinedButton(onClick = { vm.showEvent(e.slug) }, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) { Text("Refresh event & responses") }
    }
}
@Composable private fun Metric(label: String, value: Int) { Column { Text(value.toString(), fontSize = 28.sp, fontFamily = FontFamily.Serif); Text(label, style = MaterialTheme.typography.labelMedium) } }

@Composable private fun EditorScreen(vm: PartyModel) {
    val e = vm.editor ?: return
    val context = LocalContext.current
    var backgroundPhoto by remember { mutableStateOf(false) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri -> if (uri != null) vm.upload(uri, backgroundPhoto) }
    fun update(change: Event) { vm.editor = change }
    Body {
        Heading("The details", "Set the scene for your gathering.")
        Field(e.name, { update(e.copy(name = it)) }, "Event name", enabled = !vm.busy)
        if (e.id.isEmpty()) Field(e.slug, { update(e.copy(slug = it)) }, "Custom URL (optional)", help = "Lowercase letters, numbers and hyphens. Leave blank to generate one.", enabled = !vm.busy)
        DateField(e.date, { update(e.copy(date = it)) }, !vm.busy)
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            TimeField(e.start_time, { update(e.copy(start_time = it)) }, "Start time", Modifier.weight(1f), !vm.busy)
            TimeField(e.end_time, { update(e.copy(end_time = it)) }, "End time (optional)", Modifier.weight(1f), !vm.busy)
        }
        Field(e.location, { update(e.copy(location = it)) }, "Location", enabled = !vm.busy)
        Field(e.description, { update(e.copy(description = it)) }, "Description", singleLine = false, help = "Markdown supported: headings, bold, links and lists.", enabled = !vm.busy)
        var limit by rememberSaveable(e.id) { mutableStateOf(e.max_guests_per_invite.toString()) }
        Field(limit, { limit = it; update(e.copy(max_guests_per_invite = it.toIntOrNull() ?: 0)) }, "Maximum guests per invitation", keyboard = KeyboardType.Number, help = "1–100 guests, including the person responding.", enabled = !vm.busy)
        Toggle("Show attendee names to guests", e.show_attendees, { update(e.copy(show_attendees = it)) }, !vm.busy)
        Heading("Make it yours", "Choose the colors, paper and type for your invitation.")
        Choices("Color palette", e.color_scheme, listOf("pink", "blue", "red", "black"), { update(e.copy(color_scheme = it)) }, !vm.busy)
        Choices("Paper background", e.background_style, listOf("linen", "gradient", "solid", "image"), { update(e.copy(background_style = it)) }, !vm.busy)
        Field(e.background_color, { update(e.copy(background_color = it)) }, "Background color (#RRGGBB)", enabled = !vm.busy)
        Field(e.accent_color, { update(e.copy(accent_color = it)) }, "Accent color (#RRGGBB)", enabled = !vm.busy)
        Choices("Type style", e.font_style, listOf("serif", "sans"), { update(e.copy(font_style = it)) }, !vm.busy)
        Choices("Envelope", e.envelope_style, listOf("classic", "minimal"), { update(e.copy(envelope_style = it)) }, !vm.busy)
        Panel {
            Text("Invitation artwork", style = MaterialTheme.typography.titleMedium)
            RemotePhoto(e.cover_image, vm.api.origin, Modifier.fillMaxWidth().height(180.dp), fit = true)
            if (e.id.isEmpty()) Text("Save this invitation, then upload your photos.", style = MaterialTheme.typography.bodySmall)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { backgroundPhoto = false; picker.launch(androidx.activity.result.PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }, enabled = !vm.busy && e.id.isNotEmpty()) { Text("Choose artwork") }
                if (e.cover_image.isNotBlank()) TextButton(onClick = { update(e.copy(cover_image = "")) }, enabled = !vm.busy) { Text("Remove") }
            }
        }
        Panel {
            Text("Background photo", style = MaterialTheme.typography.titleMedium)
            RemotePhoto(e.background_image, vm.api.origin, Modifier.fillMaxWidth().height(150.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { backgroundPhoto = true; picker.launch(androidx.activity.result.PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }, enabled = !vm.busy && e.id.isNotEmpty()) { Text("Choose background") }
                if (e.background_image.isNotBlank()) TextButton(onClick = { update(e.copy(background_image = "", background_style = "linen")) }, enabled = !vm.busy) { Text("Remove") }
            }
        }
    }
}
@Composable private fun DateField(value: String, change: (String) -> Unit, enabled: Boolean) {
    val context = LocalContext.current
    val parsed = runCatching { LocalDate.parse(value) }.getOrElse { LocalDate.now().plusDays(1) }
    Column { Field(value, change, "Date (YYYY-MM-DD)", enabled = enabled); TextButton(onClick = { DatePickerDialog(context, { _, y, m, d -> change(LocalDate.of(y, m + 1, d).toString()) }, parsed.year, parsed.monthValue - 1, parsed.dayOfMonth).show() }, enabled = enabled) { Text("Choose date") } }
}
@Composable private fun TimeField(value: String, change: (String) -> Unit, label: String, modifier: Modifier, enabled: Boolean) {
    val context = LocalContext.current
    val parsed = runCatching { LocalTime.parse(value) }.getOrElse { LocalTime.of(18, 0) }
    Column(modifier) { Field(value, change, "$label (HH:mm)", enabled = enabled); TextButton(onClick = { TimePickerDialog(context, { _, h, m -> change("%02d:%02d".format(h, m)) }, parsed.hour, parsed.minute, false).show() }, enabled = enabled) { Text("Choose time") } }
}

@Composable private fun InvitationScreen(vm: PartyModel, preview: Boolean) {
    val e = vm.event ?: return
    val context = LocalContext.current
    val accent = runCatching { Color(android.graphics.Color.parseColor(e.accent_color)) }.getOrDefault(MaterialTheme.colorScheme.primary)
    val paper = runCatching { Color(android.graphics.Color.parseColor(e.background_color)) }.getOrDefault(Color(0xFFFFF8F0))
    val font = if (e.font_style == "serif") FontFamily.Serif else FontFamily.SansSerif
    Body {
        if (preview) Text("Preview of your saved invitation. Save editor changes before previewing.", style = MaterialTheme.typography.bodySmall)
        Card(shape = RoundedCornerShape(if (e.envelope_style == "minimal") 8.dp else 24.dp), colors = CardDefaults.cardColors(containerColor = paper), modifier = Modifier.fillMaxWidth()) {
            Box {
                if (e.background_style == "image") RemotePhoto(e.background_image, vm.api.origin, Modifier.matchParentSize(), alpha = 0.22f)
                if (e.background_style == "gradient") Box(Modifier.matchParentSize().background(androidx.compose.ui.graphics.Brush.verticalGradient(listOf(paper, accent.copy(alpha = 0.12f)))))
                Column(Modifier.padding(28.dp), verticalArrangement = Arrangement.spacedBy(20.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("YOU'RE INVITED", color = accent, fontWeight = FontWeight.Medium, letterSpacing = 3.sp, style = MaterialTheme.typography.labelLarge)
                    if (e.cover_image.isNotBlank()) RemotePhoto(e.cover_image, vm.api.origin, Modifier.fillMaxWidth(), fit = true, intrinsicRatio = true)
                    Text(e.name, color = accent, fontFamily = font, style = MaterialTheme.typography.headlineLarge)
                    HorizontalDivider(color = accent.copy(alpha = 0.3f))
                    Text(dateLabel(e), color = Color(0xFF332D30), fontFamily = font)
                    Text("${timeLabel(e.start_time)}${if (e.end_time.isBlank()) "" else " – ${timeLabel(e.end_time)}"}", color = Color(0xFF332D30), fontFamily = font)
                    Text(e.location, color = Color(0xFF332D30), fontFamily = font)
                    if (e.description.isNotBlank()) MarkdownDescription(e.description, Color(0xFF332D30), font)
                    Text("Bring your favorite people. Up to ${e.max_guests_per_invite} guests per RSVP.", color = Color(0xFF655A60), style = MaterialTheme.typography.bodySmall)
                }
            }
        }
        if (!preview) {
            Button(onClick = vm::newResponse, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) { Text("RSVP") }
            OutlinedButton(onClick = vm::editSavedResponse, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) { Text(if (vm.hasSavedResponse()) "Update my RSVP" else "Already responded? Open your update link") }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { openWeb(context, "${vm.api.origin}/${e.slug}/calendar/google") }, modifier = Modifier.weight(1f)) { Text("Google Calendar") }
                OutlinedButton(onClick = { openWeb(context, "${vm.api.origin}/${e.slug}/calendar/ics") }, modifier = Modifier.weight(1f)) { Text("Calendar file") }
            }
            if (e.show_attendees && vm.attendees.isNotEmpty()) Panel {
                Text("Who's coming", style = MaterialTheme.typography.titleLarge, fontFamily = font)
                vm.attendees.forEach { person -> Text("${person.first_name} ${person.last_initial}.${person.guest_info}") }
            }
            TextButton(onClick = { share(context, "You're invited to ${e.name}! ${eventURL(vm, e)}") }, modifier = Modifier.fillMaxWidth()) { Text("Share invitation") }
            TextButton(onClick = vm::home, enabled = !vm.busy) { Text(if (vm.session?.admin != null) "Host dashboard" else "Host sign-in") }
        } else OutlinedButton(onClick = { openWeb(context, eventURL(vm, e)) }, enabled = !e.archived, modifier = Modifier.fillMaxWidth()) { Text("Open published invitation in browser") }
    }
}
@Composable private fun MarkdownDescription(markdown: String, color: Color, font: FontFamily) {
    // Keep invitations readable without executing or embedding user-authored HTML.
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        markdown.lines().forEach { line ->
            val heading = line.takeWhile { it == '#' }.length
            val clean = line.removePrefix("#".repeat(heading)).trimStart().replace(Regex("\\[([^]]+)]\\(([^)]+)\\)"), "$1 ($2)").replace("**", "").replace("__", "")
            if (clean.isNotEmpty()) Text(clean, color = color, fontFamily = font, fontWeight = if (heading > 0) FontWeight.Bold else FontWeight.Normal, style = if (heading > 0) MaterialTheme.typography.titleMedium else MaterialTheme.typography.bodyLarge)
        }
    }
}

@Composable private fun ResponseScreen(vm: PartyModel) {
    val e = vm.event ?: return
    val r = vm.response ?: Response()
    var name by rememberSaveable(e.slug, vm.responseToken) { mutableStateOf(r.name) }
    var email by rememberSaveable(e.slug, vm.responseToken) { mutableStateOf(r.email) }
    var attending by rememberSaveable(e.slug, vm.responseToken) { mutableStateOf(r.attending) }
    var adults by rememberSaveable(e.slug, vm.responseToken) { mutableStateOf(r.num_adults.coerceAtLeast(1).toString()) }
    var children by rememberSaveable(e.slug, vm.responseToken) { mutableStateOf(r.num_children.toString()) }
    var dietary by rememberSaveable(e.slug, vm.responseToken) { mutableStateOf(r.dietary_restrictions) }
    var comment by rememberSaveable(e.slug, vm.responseToken) { mutableStateOf(r.comment) }
    Body {
        Heading(e.name, "Let your host know if you can make it.")
        Field(name, { name = it }, "Your name", enabled = !vm.busy)
        Field(email, { email = it }, "Email address", keyboard = KeyboardType.Email, enabled = !vm.busy, help = "Your private RSVP update link will be sent here.")
        Choices("Will you attend?", attending, listOf("yes", "no"), { attending = it }, !vm.busy)
        if (attending == "yes") {
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) { Field(adults, { adults = it }, "Adults", Modifier.weight(1f), !vm.busy, keyboard = KeyboardType.Number); Field(children, { children = it }, "Children", Modifier.weight(1f), !vm.busy, keyboard = KeyboardType.Number) }
            Text("Up to ${e.max_guests_per_invite} guests, including you.", style = MaterialTheme.typography.bodySmall)
            Field(dietary, { dietary = it }, "Dietary restrictions (optional)", singleLine = false, enabled = !vm.busy)
        }
        Field(comment, { comment = it }, "Note to your host (optional)", singleLine = false, enabled = !vm.busy)
        Button(onClick = { vm.saveResponse(Response(name = name, email = email, attending = attending, num_adults = adults.toIntOrNull() ?: -1, num_children = children.toIntOrNull() ?: -1, dietary_restrictions = dietary, comment = comment)) }, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) { Text(if (vm.busy) "Saving…" else if (vm.responseToken != null) "Save RSVP changes" else "Send RSVP") }
        Text("Your email address and notes are visible only to the hosts. If the host enables the attendee list, only your first name, last initial and party size are shared.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable private fun SettingsScreen(vm: PartyModel, activity: Activity, ask: (String, () -> Unit) -> Unit) {
    val context = LocalContext.current
    val admin = vm.session?.admin ?: return
    var name by rememberSaveable(admin.id) { mutableStateOf(admin.name) }
    var passkeyName by rememberSaveable { mutableStateOf("Android passkey") }
    var inviteName by rememberSaveable { mutableStateOf("") }
    val shareLink: (String) -> Unit = { share(context, it, "Share private administrator link") }
    Body {
        Heading("Your account", if (admin.is_owner) "Workspace owner" else "Administrator")
        Field(name, { name = it }, "Your display name", enabled = !vm.busy)
        OutlinedButton(onClick = { vm.settingsAction("/admin/accounts/update", payload("name" to name.trim())) }, enabled = !vm.busy && name.isNotBlank()) { Text("Save name") }
        Panel {
            Text("Your passkeys", style = MaterialTheme.typography.titleLarge)
            Field(passkeyName, { passkeyName = it }, "New passkey label", enabled = !vm.busy)
            Button(onClick = { vm.registerPasskey(activity, passkeyName) }, enabled = !vm.busy) { Text("Add passkey on this device") }
            vm.passkeys.forEach { key ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) { Text(key.string("name")); Text("Added ${key.string("created_at").substringBefore('T')}", style = MaterialTheme.typography.bodySmall) }
                    TextButton(onClick = { ask("Remove this passkey?") { vm.settingsAction("/admin/passkey/delete", payload("credential_id" to key.string("credential_id"))) } }, enabled = !vm.busy && vm.passkeys.size > 1) { Text("Remove") }
                }
            }
            if (vm.passkeys.size <= 1) Text("Keep at least one passkey. Add a backup before removing your last key.", style = MaterialTheme.typography.bodySmall)
        }
        if (admin.is_owner) {
            Heading("People", "Invite collaborators and manage their access.")
            vm.settings.rows("accounts").forEach { account ->
                Panel {
                    var newName by rememberSaveable(account.string("id")) { mutableStateOf(account.string("name")) }
                    val owner = account["is_owner"]?.jsonPrimitive?.booleanOrNull == true
                    Text(if (owner) "Owner" else "Administrator", style = MaterialTheme.typography.labelLarge)
                    Field(newName, { newName = it }, "Display name", enabled = !vm.busy)
                    Text("${account.string("passkey_count")} passkeys · Last sign-in ${account.string("last_login_at").substringBefore('T').ifEmpty { "Never" }}", style = MaterialTheme.typography.bodySmall)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        TextButton(onClick = { vm.settingsAction("/admin/accounts/update", payload("admin_id" to account.string("id"), "name" to newName)) }, enabled = !vm.busy && newName.isNotBlank()) { Text("Rename") }
                        TextButton(onClick = { vm.settingsAction("/admin/signin-links/create", payload("admin_id" to account.string("id")), shareLink) }, enabled = !vm.busy) { Text("Share one-use sign-in") }
                        TextButton(onClick = { ask("Sign out all sessions for ${account.string("name")}?") { vm.settingsAction("/admin/accounts/sessions/revoke", payload("admin_id" to account.string("id"))) } }, enabled = !vm.busy) { Text("Revoke sessions") }
                        if (!owner) TextButton(onClick = { ask("Remove ${account.string("name")} from this workspace?") { vm.settingsAction("/admin/accounts/revoke", payload("admin_id" to account.string("id"))) } }, enabled = !vm.busy) { Text("Remove access") }
                    }
                }
            }
            Panel {
                Text("Invite an administrator", style = MaterialTheme.typography.titleLarge)
                Field(inviteName, { inviteName = it }, "Invitation label", enabled = !vm.busy)
                Button(onClick = { vm.settingsAction("/admin/invites/create", payload("name" to inviteName.trim()), shareLink) }, enabled = !vm.busy && inviteName.isNotBlank()) { Text("Create & share invitation") }
                vm.invites.forEach { invite ->
                    Column {
                        Text(invite.string("name")); Text("Expires ${invite.string("expires_at").substringBefore('T')}", style = MaterialTheme.typography.bodySmall)
                        Row { TextButton(onClick = { share(context, "${vm.api.origin}/admin/invite/${invite.string("token")}", "Share administrator invitation") }, enabled = !vm.busy) { Text("Share") }; TextButton(onClick = { ask("Revoke this administrator invitation?") { vm.settingsAction("/admin/invites/delete", payload("token" to invite.string("token"))) } }, enabled = !vm.busy) { Text("Revoke") } }
                    }
                }
            }
            val links = vm.settings.rows("signin_links")
            if (links.isNotEmpty()) Panel {
                Text("Active one-use links", style = MaterialTheme.typography.titleLarge)
                links.forEach { link -> Row(verticalAlignment = Alignment.CenterVertically) {
                    val person = vm.settings.rows("accounts").firstOrNull { it.string("id") == link.string("admin_id") }?.string("name") ?: "Administrator"
                    Column(Modifier.weight(1f)) { Text(person); Text("Expires ${link.string("expires_at").replace('T', ' ').substringBefore('.')}", style = MaterialTheme.typography.bodySmall) }
                    TextButton(onClick = { ask("Revoke $person's sign-in link?") { vm.settingsAction("/admin/signin-links/delete", payload("id" to link.string("id"))) } }, enabled = !vm.busy) { Text("Revoke") }
                } }
            }
        }
        OutlinedButton(onClick = { ask("Sign out all your devices?") { vm.settingsAction("/admin/accounts/sessions/revoke", payload()) } }, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) { Text("Sign out all my sessions") }
        OutlinedButton(onClick = vm::logout, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) { Text("Sign out this device") }
        TextButton(onClick = vm::showSettings, enabled = !vm.busy) { Text("Refresh access settings") }
        Row { TextButton(onClick = { openWeb(context, "${vm.api.origin}/privacy") }) { Text("Privacy") }; TextButton(onClick = { openWeb(context, "${vm.api.origin}/terms") }) { Text("Terms") } }
    }
}

@Composable private fun RemotePhoto(path: String, origin: String, modifier: Modifier, alpha: Float = 1f, fit: Boolean = false, intrinsicRatio: Boolean = false) {
    if (path.isBlank()) return
    val safePath = path.takeIf { Regex("/media/[a-fA-F0-9]+\\.webp").matches(it) } ?: return
    val bitmap by produceState<android.graphics.Bitmap?>(null, safePath, origin) {
        value = withContext(Dispatchers.IO) {
            runCatching {
                val c = URL(origin + safePath).openConnection() as HttpURLConnection
                c.instanceFollowRedirects = false; c.connectTimeout = 15_000; c.readTimeout = 15_000
                try {
                    if (c.responseCode != 200) return@runCatching null
                    val bytes = c.inputStream.use { input ->
                        val out = ByteArrayOutputStream(); val buffer = ByteArray(8192)
                        while (true) { val count = input.read(buffer); if (count < 0) break; if (out.size() + count > 10 * 1024 * 1024) return@runCatching null; out.write(buffer, 0, count) }; out.toByteArray()
                    }
                    if (bytes.size > 10 * 1024 * 1024) return@runCatching null
                    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
                    val options = BitmapFactory.Options().apply { inSampleSize = maxOf(bounds.outWidth, bounds.outHeight).div(1600).coerceAtLeast(1) }
                    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)
                } finally { c.disconnect() }
            }.getOrNull()
        }
    }
    bitmap?.let { Image(it.asImageBitmap(), contentDescription = "Invitation artwork", modifier = if (intrinsicRatio) modifier.aspectRatio(it.width.toFloat() / it.height.coerceAtLeast(1)) else modifier, contentScale = if (fit) ContentScale.Fit else ContentScale.Crop, alpha = alpha) }
}

/** Authenticated HTML is fetched by the secure API client. The preview has no session cookie,
 * filesystem access or native JS bridge, and can request only static/media assets. */
@Composable private fun RenderedPreview(vm: PartyModel) {
    val html = vm.previewHtml ?: return
    Column(Modifier.fillMaxSize()) {
        Text("Your saved design, including the envelope animation. Responses are disabled in preview.", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(16.dp))
        AndroidView(modifier = Modifier.fillMaxSize(), factory = { context ->
            WebView(context).apply {
                settings.javaScriptEnabled = true
                settings.allowFileAccess = false
                settings.allowContentAccess = false
                settings.domStorageEnabled = false
                settings.mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
                settings.safeBrowsingEnabled = true
                CookieManager.getInstance().setAcceptCookie(false)
                CookieManager.getInstance().setAcceptThirdPartyCookies(this, false)
                webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean = true
                    override fun shouldInterceptRequest(view: WebView?, request: WebResourceRequest?): WebResourceResponse? {
                        val url = request?.url?.toString().orEmpty()
                        val path = request?.url?.path.orEmpty()
                        return if (request?.method == "GET" && Links.safeWeb(url, vm.api.origin) && (path.startsWith("/static/") || path.startsWith("/media/"))) null
                        else WebResourceResponse("text/plain", "UTF-8", ByteArrayInputStream(ByteArray(0)))
                    }
                }
                loadDataWithBaseURL(vm.api.origin + "/", html, "text/html", "UTF-8", null)
            }
        }, onRelease = { web -> web.stopLoading(); web.loadUrl("about:blank"); web.clearCache(true); web.clearHistory(); web.destroy() })
    }
}
