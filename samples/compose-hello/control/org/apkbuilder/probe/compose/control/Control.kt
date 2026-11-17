package org.apkbuilder.probe.compose.control

import androidx.compose.runtime.Composable

/**
 * Control for the Compose plugin test: a @Composable function that calls no library code, so it compiles with
 * and without the plugin. With the plugin its JVM signature gains a Composer and an Int parameter:
 *   without: label(Ljava/lang/String;)Ljava/lang/String;
 *   with:    label(Ljava/lang/String;Landroidx/compose/runtime/Composer;I)Ljava/lang/String;
 */
@Composable
fun label(text: String): String = "[" + text + "]"
