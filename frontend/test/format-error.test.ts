import { describe, expect, it } from "vitest";
import { errorMessage, errorStatusCode } from "../app/utils/format";

describe("API error formatting", () => {
  it("never renders a boolean error flag as text", () => {
    const error = {
      data: {
        error: true,
        statusCode: 502,
      },
    };

    expect(errorMessage(error, "Сервис недоступен")).toBe("Сервис недоступен");
    expect(errorStatusCode(error)).toBe(502);
  });

  it("preserves a meaningful backend error", () => {
    const error = {
      data: {
        error: "Неверный логин или пароль",
      },
      response: {
        status: 401,
      },
    };

    expect(errorMessage(error)).toBe("Неверный логин или пароль");
    expect(errorStatusCode(error)).toBe(401);
  });
});
