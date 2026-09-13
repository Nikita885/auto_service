package ru.autoservice.client.util;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/**
 * Тесты маски номера.
 *
 * <p>Первый же баг в поле ввода был ровно здесь: префикс «+7» из самого поля
 * попадал в номер первой цифрой, и семёрка «не удалялась». Проверяется не
 * внешний вид, а разбор — то, что глазами при беглом тесте не видно.
 *
 * <p>Имена методов латиницей: кириллица в идентификаторах Java допустима, но
 * ломается на несовпадении кодировок инструментов, и тест перестаёт
 * загружаться вовсе. Что именно проверяется, сказано в комментарии.
 */
public class PhoneFormatTest {

    /* ----------------------------------------------------- набор с нуля */

    /** Пустое поле — это префикс, а не пустая строка: иначе непонятно, что вводить. */
    @Test
    public void emptyInputKeepsPrefix() {
        assertEquals("+7", PhoneFormat.format(PhoneFormat.digitsOf("")));
        assertEquals("+7", PhoneFormat.format(PhoneFormat.digitsOf("+7")));
    }

    /**
     * Человек напечатал 9 в поле «+7» — получилось «+79».
     * Девятка обязана стать первой цифрой номера, а семёрка остаться префиксом.
     * Именно здесь был баг «появляется 7 и не удаляется».
     */
    @Test
    public void firstDigitIsNotConfusedWithCountryCode() {
        assertEquals("9", PhoneFormat.digitsOf("+79"));
        assertEquals("+7 (9", PhoneFormat.format(PhoneFormat.digitsOf("+79")));
    }

    /** Номера на 7 существуют: +7 (700) … — первую цифру отрезать нельзя. */
    @Test
    public void leadingSevenInNumberSurvives() {
        assertEquals("7001112233", PhoneFormat.digitsOf("+77001112233"));
    }

    /** То же для +7 (800) …: это номер, а не код страны. */
    @Test
    public void leadingEightInNumberSurvives() {
        assertEquals("8001112233", PhoneFormat.digitsOf("+78001112233"));
    }

    /** Маска собирается по мере ввода, а не только на полном номере. */
    @Test
    public void maskGrowsWhileTyping() {
        // Скобка закрывается сразу после кода — дальше идут цифры номера.
        assertEquals("+7 (900)", PhoneFormat.format("900"));
        assertEquals("+7 (900) 1", PhoneFormat.format("9001"));
        assertEquals("+7 (900) 111", PhoneFormat.format("900111"));
        assertEquals("+7 (900) 111-22", PhoneFormat.format("90011122"));
        assertEquals("+7 (900) 111-22-33", PhoneFormat.format("9001112233"));
    }

    /* -------------------------------------------------------- удаление */

    /** Стёрли последний символ — номер укорачивается, а не перестраивается. */
    @Test
    public void backspaceShortensNumber() {
        String afterBackspace = "+7 (900) 111-22-3";
        assertEquals("900111223", PhoneFormat.digitsOf(afterBackspace));
        assertEquals("+7 (900) 111-22-3", PhoneFormat.format(PhoneFormat.digitsOf(afterBackspace)));
    }

    /** Стёрли всё — остаётся префикс, поле не становится пустым. */
    @Test
    public void erasingEverythingLeavesPrefix() {
        assertEquals("", PhoneFormat.digitsOf("+"));
        assertEquals("+7", PhoneFormat.format(PhoneFormat.digitsOf("+")));
    }

    /* --------------------------------------------- вставка из буфера */

    /**
     * Вставка в любом написании даёт один номер — иначе один человек
     * завёл бы несколько аккаунтов.
     */
    @Test
    public void pasteInAnyNotationGivesSameNumber() {
        String expected = "9001112233";

        assertEquals(expected, PhoneFormat.digitsOf("+7+7 900 111-22-33"));
        assertEquals(expected, PhoneFormat.digitsOf("+78 (900) 111 22 33"));
        assertEquals(expected, PhoneFormat.digitsOf("+79001112233"));
        assertEquals(expected, PhoneFormat.digitsOf("+7 900 111 22 33"));
    }

    /** Лишние цифры сверх десяти отбрасываются, а не уезжают в номер. */
    @Test
    public void extraDigitsAreDropped() {
        assertEquals("9001112233", PhoneFormat.digitsOf("+7 (900) 111-22-3399999"));
    }

    /* ------------------------------------------------------ готовность */

    /** Кнопка активна только на полном номере: на обрывке сервер вернёт ошибку. */
    @Test
    public void completeOnlyWithTenDigits() {
        assertFalse(PhoneFormat.isComplete("+7"));
        assertFalse(PhoneFormat.isComplete("+7 (900) 111-22-3"));
        assertTrue(PhoneFormat.isComplete("+7 (900) 111-22-33"));
    }

    /** На сервер уходит E.164 — тот же вид, в котором он хранит телефон. */
    @Test
    public void sendsE164ToServer() {
        assertEquals("+79001112233", PhoneFormat.toE164("+7 (900) 111-22-33"));
        assertEquals("", PhoneFormat.toE164("+7"));
    }

    /* ---------------------------------------------------------- курсор */

    /** Курсор встаёт за последней цифрой, а не за скобкой. */
    @Test
    public void cursorGoesAfterLastDigit() {
        assertEquals(7, PhoneFormat.cursorAfterDigits("+7 (900", 3));
        assertEquals(10, PhoneFormat.cursorAfterDigits("+7 (900) 1", 4));
    }

    /** Без введённых цифр курсор в конце префикса. */
    @Test
    public void cursorAtEndWhenNoDigits() {
        assertEquals(2, PhoneFormat.cursorAfterDigits("+7", 0));
    }
}
