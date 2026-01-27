import axios, { AxiosInstance, AxiosError } from 'axios';
import { API_CONFIG } from '../config/constants';
import type { UploadResponse, StatusResponse, ResultResponse } from '../types';

class ApiError extends Error {
  constructor(
    public statusCode: number | null,
    public originalError: AxiosError | Error,
    message: string
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

const api: AxiosInstance = axios.create({
  baseURL: API_CONFIG.BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const statusCode = error.response?.status || null;
    const message = (error.response?.data as any)?.detail || 
                   error.message || 
                   'An unknown error occurred';
    
    throw new ApiError(statusCode, error, message);
  }
);

export const uploadFile = async (
  file: File,
  locale: string = 'en-IN',
  context: 'report' | 'prescription' | 'auto' = 'auto'
): Promise<UploadResponse> => {
  try {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('locale', locale);
    formData.append('context', context);

    const response = await api.post<UploadResponse>('/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });

    return response.data;
  } catch (error) {
    throw error;
  }
};

export const getStatus = async (jobId: string): Promise<StatusResponse> => {
  try {
    const response = await api.get<StatusResponse>(`/status/${jobId}`);
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const getResult = async (jobId: string): Promise<ResultResponse> => {
  try {
    const response = await api.get<ResultResponse>(`/result/${jobId}`);
    return response.data;
  } catch (error) {
    throw error;
  }
};

export default api;
