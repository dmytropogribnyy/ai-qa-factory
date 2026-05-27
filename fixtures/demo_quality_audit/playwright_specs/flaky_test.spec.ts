import { test, expect } from '@playwright/test';

/**
 * Demo fixture — flaky test patterns.
 * Contains intentional anti-patterns for Phase 5O analyzer demonstration:
 * - waitForTimeout() hard wait
 * - .nth() positional selector
 * - xpath= fragile selector
 * - dynamic CSS class with numeric suffix
 * - waitForSelector() non-web-first assertion
 * - page.goto() without waitUntil
 * This file is used by the Phase 5O flaky test analyzer as a "bad patterns" baseline.
 */

const BASE = 'https://demo.playwright.dev/todomvc';

test.describe('TodoMVC — flaky examples (anti-patterns)', () => {

  test('add item using hard wait', async ({ page }) => {
    await page.goto(BASE);
    await page.waitForTimeout(2000);
    await page.locator('input.new-todo').fill('Buy milk');
    await page.locator('input.new-todo').press('Enter');
    await page.waitForTimeout(1000);
    await expect(page.locator('.todo-list li').nth(0)).toBeVisible();
  });

  test('click item using nth positional selector', async ({ page }) => {
    await page.goto(BASE);
    await page.locator('input.new-todo').fill('First task');
    await page.locator('input.new-todo').press('Enter');
    await page.locator('input.new-todo').fill('Second task');
    await page.locator('input.new-todo').press('Enter');
    // Fragile: depends on DOM order
    const secondItem = page.locator('.todo-list li').nth(1);
    await expect(secondItem).toBeVisible();
    await secondItem.locator('.toggle').click();
  });

  test('find element using xpath selector', async ({ page }) => {
    await page.goto(BASE);
    await page.locator('input.new-todo').fill('XPath task');
    await page.locator('input.new-todo').press('Enter');
    // Fragile XPath
    const item = page.locator('xpath=//ul[@class="todo-list"]/li[1]/div/label');
    await expect(item).toBeVisible();
  });

  test('target element with dynamic generated class', async ({ page }) => {
    await page.goto(BASE);
    // Fragile: class with numeric suffix (auto-generated)
    const wrapper = page.locator('.todoapp-container487');
    // If element does not exist, test may silently pass or fail depending on state
    const count = await wrapper.count();
    expect(count).toBeGreaterThanOrEqual(0);
  });

  test('wait for selector instead of web-first assertion', async ({ page }) => {
    await page.goto(BASE);
    await page.locator('input.new-todo').fill('Selector task');
    await page.locator('input.new-todo').press('Enter');
    // Non-web-first assertion — prefer expect(locator).toBeVisible()
    await page.waitForSelector('.todo-list li');
    const items = page.locator('.todo-list li');
    expect(await items.count()).toBeGreaterThan(0);
  });

  test('nested nth combinator', async ({ page }) => {
    await page.goto(BASE);
    await page.locator('input.new-todo').fill('Combo task');
    await page.locator('input.new-todo').press('Enter');
    // Fragile: >> nth= combinator
    const label = page.locator('.todo-list >> nth=0 >> label');
    await expect(label).toBeVisible();
  });

});
