/**
 * Centralized API client with error handling and logging
 */

interface ApiError {
  status: number;
  message: string;
  timestamp: string;
}

export class ApiClientError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiClientError';
  }
}

class ApiClient {
  private static instance: ApiClient;
  private baseUrl = '';

  private constructor() {}

  static getInstance(): ApiClient {
    if (!ApiClient.instance) {
      ApiClient.instance = new ApiClient();
    }
    return ApiClient.instance;
  }

  private logError(method: string, url: string, error: unknown, status?: number): void {
    const timestamp = new Date().toISOString();
    const errorMsg = error instanceof Error ? error.message : String(error);
    console.error(`[API Error ${timestamp}] ${method} ${url} (${status || 'unknown'})`, errorMsg);
  }

  private async handleResponse<T>(res: Response): Promise<T> {
    if (!res.ok) {
      const error: ApiError = {
        status: res.status,
        message: `${res.status}: ${res.statusText}`,
        timestamp: new Date().toISOString(),
      };
      
      try {
        const body = await res.json();
        error.message = body.error || error.message;
      } catch {
        // Response is not JSON, use status text
      }

      throw new ApiClientError(res.status, error.message);
    }

    try {
      return await res.json() as T;
    } catch (error) {
      this.logError('JSON Parse', res.url, error);
      throw new Error('Failed to parse response');
    }
  }

  async get<T>(url: string, options?: RequestInit): Promise<T> {
    try {
      const res = await fetch(`${this.baseUrl}${url}`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          ...options?.headers,
        },
        ...options,
      });
      return this.handleResponse<T>(res);
    } catch (error) {
      if (error instanceof ApiClientError) {
        this.logError('GET', url, error, error.status);
      } else {
        this.logError('GET', url, error);
      }
      throw error;
    }
  }

  async post<T>(url: string, body?: unknown, options?: RequestInit): Promise<T> {
    try {
      const res = await fetch(`${this.baseUrl}${url}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...options?.headers,
        },
        body: body ? JSON.stringify(body) : undefined,
        ...options,
      });
      return this.handleResponse<T>(res);
    } catch (error) {
      if (error instanceof ApiClientError) {
        this.logError('POST', url, error, error.status);
      } else {
        this.logError('POST', url, error);
      }
      throw error;
    }
  }

  async put<T>(url: string, body?: unknown, options?: RequestInit): Promise<T> {
    try {
      const res = await fetch(`${this.baseUrl}${url}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...options?.headers,
        },
        body: body ? JSON.stringify(body) : undefined,
        ...options,
      });
      return this.handleResponse<T>(res);
    } catch (error) {
      if (error instanceof ApiClientError) {
        this.logError('PUT', url, error, error.status);
      } else {
        this.logError('PUT', url, error);
      }
      throw error;
    }
  }

  async delete<T>(url: string, options?: RequestInit): Promise<T> {
    try {
      const res = await fetch(`${this.baseUrl}${url}`, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
          ...options?.headers,
        },
        ...options,
      });
      return this.handleResponse<T>(res);
    } catch (error) {
      if (error instanceof ApiClientError) {
        this.logError('DELETE', url, error, error.status);
      } else {
        this.logError('DELETE', url, error);
      }
      throw error;
    }
  }
}

export const api = ApiClient.getInstance();
